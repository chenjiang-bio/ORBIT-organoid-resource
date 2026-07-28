#!/usr/bin/env python
import json
import traceback
import warnings
import glob

# from datetime import datetime

# from organoid_info_extract.crew import OrganoidInfoExtract
from pydantic import BaseModel

from crewai_tools import MCPServerAdapter
from crewai.crews.crew_output import CrewOutput
from crewai.flow.flow import Flow, listen, start, router, or_
from .beam.organoid_culture import ExtractionResult,  DataSearchCheckResult, DataCheckResult, JudgementResult, DataSearchResult, DataSearchPlan

from mcp import StdioServerParameters # Needed for Stdio example
from typing import Any, List, Dict

import os
import re
import shutil

from .utils.listening import AgentLogsListener
from .utils.webhook_notify import send_text_message_to_notify_url
from .utils.json_diff import json_diff


from .process.crew_extract import CrewDataExtractor
from .process.crew_check import CrewDataCheckers
from .process.crew_search import CrewDataSearcherPlan, CrewDataSearcherExecute
from .process.crew_correct import CrewDataCorrectors
from .process.crew_judge import CrewDataJudger

from .config import GLOBAL_TOOLS_CONFIG

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

from fastmcp import Client
import asyncio

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

async def search_doi(server_url:str, text: str) -> List[str]:
    client = Client(server_url)
    dois = []
    async with client:
        result = await client.call_tool("get_pubmed_article_by_text", {
            "texts": [
                text
            ]
        })
        import json
        article_model = json.loads(result.content[0].text)
        print(article_model)
        for article in article_model:
            infos = article["infos"]
            infos = json.loads(infos) if isinstance(infos, str) else infos
            if isinstance(infos, dict):
                error = infos.get("error", None)
                if error:
                    # print(f"Error: {error}")
                    continue
                dois.append(infos.get("doi", ""))
            elif isinstance(infos, list) or isinstance(infos, tuple):
                for item in infos:
                    dois.append(item.get("doi", ""))
            # else:
                # print(f"Unexpected infos format: {type(infos)}")
            # print("-" * 20)
    return dois


class ExtractInfo(BaseModel):
    work_name:str = ""  # The name of this extraction work
    query_input_path: str = ""  # the directory of the Original Text(Markdown) file
    tentative_output_filepath: str = ""  # Tentative Output JSON file path
    check_output_filepath: str = ""  # Data check result
    search_plan_output_filepath: str = ""  # Data search plan result
    search_output_filepath: str = ""  # Data search result
    final_output_filepath: str = ""  # Final Output JSON file path
    topic: str = ""  # The topic of the original text
    original_text: str = ""
    siliconcyte_server_params: StdioServerParameters | dict[str, Any] | list[StdioServerParameters | dict[str, Any]] = []  # The siliconcyte MCP server parameters
    log_dir_path: str = ""  # The log directory path {subfile will be created inside by crew}
    real_log_dir_path: str = ""  # The log directory path {subfile will be created inside by crew}: log_dir_path + uuid


agentLogsListener = AgentLogsListener()


class FileBaseModelTool:
    def __init__(self, model_class: type, file_path: str):
        self.model_class = model_class
        self.file_path = file_path
    
    def is_exist(self) -> bool:
        return os.path.exists(self.file_path)

    def is_valid(self) -> bool:
        try:
            self.model_validate()
            return True
        except FileExistsError as fee:
            return False
        except Exception as e:
            print(f"Model validation failed for file {self.file_path}: {e}")
            return False

    def model_validate(self):
        if not self.is_exist():
            raise FileExistsError(f"File {self.file_path} does not exist.")
        with open(self.file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        return self.model_class.model_validate(json_data)
        
    def model_validate_json(self) -> dict:
        if not self.is_exist():
            raise FileExistsError(f"File {self.file_path} does not exist.")
        with open(self.file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
            self.model_class.model_validate(json_data)
            return json_data
    
    def dump(self, data):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data.model_dump(), f, indent=2, ensure_ascii=False)
    
    def dump_json(self, data: dict):
        model = self.model_class.model_validate(data)
        self.dump(model)


class MultiFileBaseModelTool:
    def __init__(self, model_class: type, file_path_pattern: str):
        self.model_class = model_class
        self.file_path_pattern = file_path_pattern
        self.dir_path = os.path.dirname(file_path_pattern)
        self.file_name = os.path.basename(file_path_pattern)
        self.real_files_path = []
        self.real_files_name = []
        self._checkers = {}
        for file_path in glob.glob(file_path_pattern):
            file_name = os.path.basename(file_path)
            self.real_files_path.append(file_path)
            self.real_files_name.append(file_name)
            self._checkers[file_name] = FileBaseModelTool(model_class, file_path)
    
    def n_valid(self) -> int:
        count = 0
        for checker in self._checkers.values():
            if checker.is_valid():
                count += 1
        return count

    def model_validate(self) -> dict:
        results = {}
        for filename, checker in self._checkers.items():
            result = checker.model_validate()
            if result is not None:
                results[filename] = result
        return results
    
    def model_validate_json(self) -> dict:
        results = {}
        for filename, checker in self._checkers.items():
            result = checker.model_validate_json()
            if result is not None:
                results[filename] = result
        return results
    
    def dump(self, name: str, data):
        if name in self._checkers:
            self._checkers[name].dump(data)
        else:
            file_path = os.path.join(self.dir_path, f"{self.file_name.replace('*', name)}")
            checker = FileBaseModelTool(self.model_class, file_path)
            checker.dump(data)
            self._checkers[name] = checker
            self.real_files_path.append(file_path)
            self.real_files_name.append(name)
    
            
class ExtractInfoFlow(Flow[ExtractInfo]):
    @start()
    def start_method(self):
        print(f"Starting the structured flow: {self.flow_id}")
        # self.state.real_log_dir_path = os.path.join(self.state.log_dir_path, f"{self.flow_id}")
        # os.makedirs(self.state.real_log_dir_path, exist_ok=True)
        self.state.real_log_dir_path = os.path.join(self.state.log_dir_path, f"{self.state.work_name}.md")
        agentLogsListener.set_log_path(self.state.real_log_dir_path)
        agentLogsListener.start(self.flow_id)

        # Read original text
        print(f"Load original text from {self.state.query_input_path}")
        with open(self.state.query_input_path, 'r', encoding='utf-8') as f:
            self.state.original_text = f.read()
        
    
    @router(start_method)
    async def extract(self):
        final_handle = FileBaseModelTool(ExtractionResult, self.state.final_output_filepath)
        if final_handle.is_valid():
            print(f"[====> EXTRACT] Final file {self.state.final_output_filepath} already exists and seems valid. Skip extraction step.")
            return "end"

        extract_handle = FileBaseModelTool(ExtractionResult, self.state.tentative_output_filepath)
        if extract_handle.is_valid():
            print(f"[====> EXTRACT] Tentative file {self.state.tentative_output_filepath} already exists and seems valid. Skip extraction step.")
            return "route_to_check"
        # crew_extract.py
        # with MCPServerAdapter(self.state.siliconcyte_server_params) as tools:
        result = CrewDataExtractor().run(
            work_name=self.state.work_name,
            topic=self.state.topic,
            original_text=self.state.original_text,
            max_retry_count=6,
            tools=None
        )
        # save tentative output
        extract_handle.dump(result.pydantic)
        print(f"[====> EXTRACT] Multi-step extraction mode: saving tentative output to {self.state.tentative_output_filepath}")
        return "route_to_check"
        
        

    @listen("route_to_check")
    async def check(self):
        # if final, skip.
        search_check_handler = FileBaseModelTool(DataSearchCheckResult, self.state.check_output_filepath)
        if search_check_handler.is_valid():
            print(f"[====> CHECK] Final check file {self.state.check_output_filepath} already exists and seems valid. Skip check step.")
            return {"check_search_result": search_check_handler.model_validate_json()}
        
        # 0. load tentative output
        tentative_handle = FileBaseModelTool(ExtractionResult, self.state.tentative_output_filepath)
        extract_json = tentative_handle.model_validate_json()
        if "puzzles" in extract_json:
            del extract_json["puzzles"]  # remove puzzles before check
        # 1. search plan
        search_plan_handle = FileBaseModelTool(DataSearchPlan, self.state.search_plan_output_filepath)
        if not search_plan_handle.is_valid():
            print(f"[====> SEARCH PLAN] Generating search plan...")
            plan_result = CrewDataSearcherPlan().run(
                work_name=self.state.work_name,
                topic=self.state.topic,
                original_text=self.state.original_text,
                extract_result=extract_json,
                max_retry_count=3
            )
            # Save plan result
            search_plan_handle.dump(plan_result.pydantic)
            print(f"Search plan saved to {self.state.search_plan_output_filepath}: {plan_result.pydantic.model_dump()}")
            search_plan_output_dict = plan_result.pydantic.model_dump()
        else:
            print(f"[====> SEARCH PLAN] Search plan file {self.state.search_plan_output_filepath} exists. Skip plan generation.")
            search_plan_output_dict = search_plan_handle.model_validate_json()
        
        # 2. search execute
        search_handle = FileBaseModelTool(DataSearchResult, self.state.search_output_filepath)
        if not search_handle.is_valid():
            with MCPServerAdapter(self.state.siliconcyte_server_params) as tools:
                print(f"[====> SEARCH] Ready to search data with {[tool.name for tool in tools]} tools.")
                search_result = CrewDataSearcherExecute().run(
                    work_name=self.state.work_name,
                    topic=self.state.topic,
                    search_plan=search_plan_output_dict,
                    max_retry_count=3,
                    tools=tools
                )
                # Save search result
                search_handle.dump(search_result.pydantic)
                print(f"Data search result saved to {self.state.search_output_filepath}: {search_result.pydantic.model_dump()}")
                search_output_dict = search_result.pydantic.model_dump()
        else:
            print(f"[====> SEARCH] Data search result file {self.state.search_output_filepath} exists. Skip data search step.")
            search_output_dict = search_handle.model_validate_json()
        
        
        # 3. check
        check_output_dir = os.path.dirname(self.state.check_output_filepath)
        file_name_without_ext, ext = os.path.splitext(os.path.basename(self.state.check_output_filepath))
        check_handlers = MultiFileBaseModelTool(DataCheckResult, f"{check_output_dir}/{file_name_without_ext}-*{ext}")
        if check_handlers.n_valid() < 2:  # Need at least two; otherwise treat as no result and continue
            existing_checks = check_handlers.model_validate_json()
            # Save and strip search puzzles
            search_dict_puzzles = search_output_dict["puzzles"]
            search_output_dict["puzzles"] = []
            
            # Run checkers (skip/merge existing results internally)
            result, new_check_results = await CrewDataCheckers().run(
                self.state.work_name, 
                self.state.topic, 
                self.state.original_text, 
                extract_json, 
                search_output_dict, 
                existing_checks,
                max_retry_count=3, 
                tools=None
            )
            
            # Persist each newly run checker result to its own file
            if new_check_results:
                for crew_name, check_result_data in new_check_results.items():
                    check_handlers.dump(crew_name, DataCheckResult.model_validate(check_result_data))
            
            # Restore search puzzles
            result.pydantic.search.puzzles = search_dict_puzzles
            
            # save combined check output
            search_check_handler.dump(result.pydantic)
            print(f"Combined check result saved to {self.state.check_output_filepath}:  {result.pydantic.model_dump()}")
            return {"check_search_result": search_check_handler.model_validate_json()}
        
        
    @router(check)
    def check_router(self, check_search_result):
        check_search_result_json = check_search_result.get("check_search_result", {})
        check_json = check_search_result_json.get("check", {})
        check_is_pass = check_json.get("is_pass", False)
        if check_is_pass:
            print("[====> COPY] Data check passed")
            return "route_to_copy_extract_result_to_final"
        else:
            check_errors = check_json.get("errors", None)
            if check_errors and len(check_errors)==0:
                print("[====> COPY] Data check passed. No errors found, but is_pass is False")
                return "route_to_copy_extract_result_to_final"
            
            print(f"[====> CORRECT] Data check failed. check_result = {check_json}")
            return "route_to_correct"
    
    @listen("route_to_correct")
    async def correct(self):
        file_name ,ext = os.path.splitext(os.path.basename(self.state.final_output_filepath))
        correct_handlers = MultiFileBaseModelTool(ExtractionResult, f"{os.path.dirname(self.state.final_output_filepath)}/{file_name}-*{ext}")
        if correct_handlers.n_valid() > 1:  # Multiple final results already exist; skip correction
            print(f"[====> CORRECT] Final output file with pattern {os.path.dirname(self.state.final_output_filepath)}/{file_name}-*{ext} already exists and seems valid. Skip correct step.")
            return

        extract_handler = FileBaseModelTool(ExtractionResult, self.state.tentative_output_filepath)
        search_check_handler = FileBaseModelTool(DataSearchCheckResult, self.state.check_output_filepath)

        extract_json = extract_handler.model_validate_json()
        search_check_json = search_check_handler.model_validate_json()

        # crew corrector
        if "puzzles" in extract_json:
            del extract_json["puzzles"]  # remove puzzles before correct
        del search_check_json["check"]["puzzles"]  # remove puzzles before correct
        del search_check_json["search"]["puzzles"]  # remove puzzles before correct

        # Load existing results; skip re-run / re-correction when present
        exists_result = correct_handlers.model_validate() 
        exists_result_names = set(exists_result.keys())
        print(f"Existing final output results: {exists_result}")

        final_output_results = await CrewDataCorrectors().run(self.state.work_name, self.state.topic, self.state.original_text, extract_json, search_check_json, exists_result_names, max_retry_count=3)

        if final_output_results is not None:
            for final_output_result in final_output_results:
                # save final output
                if not final_output_result:
                    continue
                print(f"final_output_result[{final_output_result.name}]: {final_output_result.result}")
                correct_handlers.dump(final_output_result.name, final_output_result.result.pydantic)


    @listen(correct)
    def final_select(self):
        final_handler = FileBaseModelTool(ExtractionResult, self.state.final_output_filepath)
        if final_handler.is_valid():
            print(f"[====> SELECT] Final output file {self.state.final_output_filepath} already exists and seems valid. Skip final selection step.")
            return
        # judge final output
        # 1. prepare multiple final outputs for selection
        final_output_dir = os.path.dirname(self.state.final_output_filepath)
        final_name_without_ext ,ext = os.path.splitext(os.path.basename(self.state.final_output_filepath))
        correct_handlers = MultiFileBaseModelTool(ExtractionResult, f"{final_output_dir}/{final_name_without_ext}-*{ext}")
        correct_jsons = correct_handlers.model_validate_json()
        if len(correct_jsons) < 2:
            raise Exception(f"Final selection failed: Not enough valid final outputs to select from.")
        # Load multiple final result files, pick one, save as self.state.final_output_filepath
        judger_content = ""
        for correct_name, correct_json in correct_jsons.items():
            if "puzzles" in correct_json:
                del correct_json["puzzles"]  # remove puzzles before judge
            judger_content += f"<Judge Name={correct_name}>"
            judger_content += json.dumps(correct_json, ensure_ascii=False) + "\n"
            judger_content += f"</Judge Name={correct_name}>\n"

        if len(correct_jsons) == 2:
            left, right = list(correct_jsons.values())[0], list(correct_jsons.values())[1]
            diff_json_result = json_diff(left, right) # JsonDiffResult
            # save diff result to json
            diff_output_path = os.path.join(final_output_dir, f"{final_name_without_ext}_diff.json")
            with open(diff_output_path, 'w', encoding='utf-8') as f:
                json.dump(diff_json_result.model_dump(), f, indent=2, ensure_ascii=False)
        
        # crew judge
        search_check_handler = FileBaseModelTool(DataSearchCheckResult, self.state.check_output_filepath)
        search_check_json = search_check_handler.model_validate_json()
        del search_check_json["check"]["puzzles"]  # remove puzzles before correct
        del search_check_json["search"]["puzzles"]  # remove puzzles before correct
        result = CrewDataJudger().run(self.state.work_name, self.state.topic, self.state.original_text, judger_content, search_check_json, max_retry_count=3)

        # save scores
        score_output_path = os.path.join(final_output_dir, f"{final_name_without_ext}_scores.json")
        score_output_handler = FileBaseModelTool(JudgementResult, score_output_path)
        
        score_output_handler.dump(result.pydantic)
        print(f"Final selection scores saved to {score_output_path}")

        # save final selection result
        score_result = result.pydantic # type: JudgementResult
        if not score_result or not score_result.judgements or len(score_result.judgements) == 0:
            raise Exception(f"Final selection failed: No judgements found in score result.")
        # Select the highest-scoring result
        max_score = -65535
        max_score_name = ""
        for judgement in score_result.judgements:
            selected_name = judgement.name
            if selected_name in correct_jsons:
                if judgement.final_score > max_score:
                    max_score = judgement.final_score
                    max_score_name = selected_name
            else:
                print(f"Selected name {selected_name} not found in valid final outputs.")
        # Write the selected result as the final output file
        if max_score_name == "":
            raise Exception(f"Final selection failed: No valid selection made.")
        
        # save final json
        final_handler.dump_json(correct_jsons[max_score_name])
        print(f"Final selected output: {max_score_name} with score {max_score}")
    
    @listen("route_to_copy_extract_result_to_final")
    def copy_extract_result_to_final(self):
        final_handle = FileBaseModelTool(ExtractionResult, self.state.final_output_filepath)
        if final_handle.is_valid():
            print(f"[====> COPY] Final file {self.state.final_output_filepath} already exists and seems valid. Skip copying tentative output to final output.")
            return
        tentative_handle = FileBaseModelTool(ExtractionResult, self.state.tentative_output_filepath)
        if not tentative_handle.is_valid():
            raise Exception(f"Tentative output file {self.state.tentative_output_filepath} does not exist or is invalid. Cannot copy to final output.")
        
        final_handle.dump_json(tentative_handle.model_validate_json())
        print(f"[====> COPY] Copied tentative output from {self.state.tentative_output_filepath} to final output {self.state.final_output_filepath}.")


    @listen(or_(final_select, copy_extract_result_to_final))
    def end(self):
        agentLogsListener.end(self.flow_id)
        print("Flow ended.")

def create_extract_info(work_name:str, input_path: str, output_dir: str, topic:str, siliconcyte_server_params:list, log_dir_path:str) -> ExtractInfo:
    """
    Get all file paths by input path.
    """
    info = ExtractInfo()
    info.work_name = work_name
    info.query_input_path = input_path
    info.tentative_output_filepath = os.path.join(output_dir, "tentative_output.json")
    info.check_output_filepath = os.path.join(output_dir, "check_output.json")
    info.search_plan_output_filepath = os.path.join(output_dir, "search_plan_output.json")
    info.search_output_filepath = os.path.join(output_dir, "search_output.json")
    info.final_output_filepath = os.path.join(output_dir, "final_output.json")
    info.original_text = "NO DATA"
    info.topic = topic
    info.siliconcyte_server_params = siliconcyte_server_params
    info.log_dir_path = log_dir_path
    return info


def run():
    """
    Run the crew.
    """
    global agentLogsListener

    config_json = os.getenv("PAPER_CONFIG_DIR", None)
    if not config_json or not os.path.exists(config_json):
        raise Exception("Please set the PAPER_CONFIG_DIR environment variable to specify the config json file.")
    config_json = json.loads(open(config_json, 'r', encoding='utf-8').read())

    data_root_dir = config_json.get("EXTRACTION_DATA_DIR", None)
    if not data_root_dir:
        raise Exception("Please set the EXTRACTION_DATA_DIR in PAPER_CONFIG_DIR config json.")
    data_output_dir = config_json.get("OUTPUT_DATA_DIR", None)
    if not data_output_dir:
        raise Exception("Please set the OUTPUT_DATA_DIR in PAPER_CONFIG_DIR config json.")
    log_dir_path = config_json.get("LOG_DIR", None)
    if not log_dir_path:
        raise Exception("Please set the LOG_DIR in PAPER_CONFIG_DIR config json.")

    print(f"Starting extraction process in directory: {data_root_dir}...")

    data_names = [d for d in os.listdir(data_root_dir) if os.path.isdir(os.path.join(data_root_dir, d))]
    
    try:
        total_count = len(data_names)
        for index, data_name in enumerate(data_names):
            try:
                content_md_path = os.path.join(data_root_dir, data_name, "content.md")
                info = create_extract_info(
                    work_name=data_name,
                    input_path=content_md_path,
                    output_dir=os.path.join(data_output_dir, data_name),
                    topic="Bio|Cell|Organoid|Medical",
                    siliconcyte_server_params=GLOBAL_TOOLS_CONFIG,
                    log_dir_path=log_dir_path,
                )
                final_checker = FileBaseModelTool(ExtractionResult, info.final_output_filepath)
                if final_checker.is_valid():
                    print(f"Final output file {info.final_output_filepath} already exists. Skipping {data_name}.")
                    continue
                send_text_message_to_notify_url(f"[{index+1}/{total_count}] 👀 Starting: {data_name}")
                
                if not os.path.exists(content_md_path):
                    send_text_message_to_notify_url(f"[{index+1}/{total_count}] ✨ Input file missing, skip: {data_name}")
                    print(f"Input file {content_md_path} does not exist. Skipping {data_name}.")
                    continue
                
                # Determine the correct npx command based on platform
                # npx_command = "npx.cmd" if platform.system() == "Windows" else "npx"
                flow = ExtractInfoFlow(**info.model_dump())
                ExtractInfoFlow.name = "ExtractInfoFlow"
                flow.kickoff()
                send_text_message_to_notify_url(f"[{index+1}/{total_count}] ✅️ Completed: {data_name}")
            except KeyboardInterrupt as kie:
                send_text_message_to_notify_url(f"[{index+1}/{total_count}] ⚠️ Interrupted by user: {data_name}")
                print("Process interrupted by user.")
                raise kie
            except Exception as e:
                send_text_message_to_notify_url(f"[{index+1}/{total_count}] ❌ Failed: {data_name}, error: {e}")
                print(f"An error occurred while processing {data_name}: {e}")
                traceback.print_exc()
                continue
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")
        
    finally:
        agentLogsListener.clean()

