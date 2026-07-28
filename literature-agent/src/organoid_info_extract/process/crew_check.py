from crewai import CrewOutput
import json

from ..utils.json_schema import SchemaWithoutDescription
from ..beam.organoid_culture import ExtractionResult, OUTPUT_INFOS, DataCheckResult, DataSearchCheckResult
from ..config import GLOBAL_AGENTS_CONFIG, GLOBAL_TASKS_CONFIG
from .crew_utils import parallel_crew, ParallelCrewConfig, OneChanceConverter

from crewai.utilities.converter import generate_model_description
from crewai.tools import BaseTool
from crewai_tools.adapters.tool_collection import ToolCollection
import os

class CrewDataCheckers():
    async def run(self, work_name:str, topic:str, original_text:str, extract_result:dict, search_result:dict, existing_checks:dict[str, dict], max_retry_count:int=3, tools:ToolCollection[BaseTool]=None) -> tuple[CrewOutput, dict[str, dict]]:
        """
        Run checkers and merge results.
        
        Args:
            existing_checks: Existing checker results as {crew_name: check_result_dict}
        
        Returns:
            tuple: (CrewOutput with merged DataSearchCheckResult, dict of newly run checker results)
        """
        init_spectific_configs = [
            {
                "llm_model":os.getenv("CHECK_API_MODEL1"),
                "task_name":os.getenv("CHECK_API_NAME1"),
                "crew_name":os.getenv("CHECK_API_NAME1"),
                "llm_api_key": os.getenv("CHECK_API_KEY1"),
                "llm_base_url": os.getenv("CHECK_API_BASEURL1"),
                "llm_temperature": float(os.getenv("CHECK_API_TEMPERATURE")),
                "llm_timeout": int(os.getenv("CHECK_API_TIMEOUT")),
                "llm_reasoning_effort": os.getenv("CHECK_API_REASONING_EFFORT"),
                "llm_num_ctx": int(os.getenv("CHECK_NUM_CTX", 262144)),
            },   
            {
                "llm_model":os.getenv("CHECK_API_MODEL2"),
                "task_name":os.getenv("CHECK_API_NAME2"),
                "crew_name":os.getenv("CHECK_API_NAME2"),
                "llm_api_key": os.getenv("CHECK_API_KEY2"),
                "llm_base_url": os.getenv("CHECK_API_BASEURL2"),
                "llm_temperature": float(os.getenv("CHECK_API_TEMPERATURE")),
                "llm_timeout": int(os.getenv("CHECK_API_TIMEOUT")),
                "llm_reasoning_effort": os.getenv("CHECK_API_REASONING_EFFORT"),
                "llm_num_ctx": int(os.getenv("CHECK_NUM_CTX", 262144)),

            },
            {
                "llm_model":os.getenv("CHECK_API_MODEL3"),
                "task_name":os.getenv("CHECK_API_NAME3"),
                "crew_name":os.getenv("CHECK_API_NAME3"),
                "llm_api_key": os.getenv("CHECK_API_KEY3"),
                "llm_base_url": os.getenv("CHECK_API_BASEURL3"),
                "llm_temperature": float(os.getenv("CHECK_API_TEMPERATURE")),
                "llm_timeout": int(os.getenv("CHECK_API_TIMEOUT")),
                "llm_reasoning_effort": os.getenv("CHECK_API_REASONING_EFFORT"),
                "llm_num_ctx": int(os.getenv("CHECK_NUM_CTX", 262144)),
            },
        ]
        
        # Expected checker name list
        expected_checker_names = {config["crew_name"] for config in init_spectific_configs}
        
        # Warn on existing_checks entries not in config (possible stale config leftovers)
        for crew_name in existing_checks.keys():
            if crew_name not in expected_checker_names:
                print(f"[WARNING] Found checker result '{crew_name}' not in current config. It will be ignored.")

        
        # Filter checkers that still need to run (no result yet)
        spectific_configs = []
        for spectific_config in init_spectific_configs:
            crew_name = spectific_config["crew_name"]
            if crew_name not in existing_checks:
                spectific_configs.append(spectific_config)
            else:
                print(f"[====> COPY] Checker '{crew_name}' result already exists. Skip running.")
        
        # Run unfinished checkers
        new_check_results = {}
        if len(spectific_configs) > 0:
            print(f"Running {len(spectific_configs)} checker(s): {[c['crew_name'] for c in spectific_configs]}")
            check_results = await parallel_crew(
                template_agent_config=ParallelCrewConfig(
                    work_name=work_name,
                    llm_model="",
                    llm_temperature=0.0,
                    llm_timeout=300,
                    llm_reasoning_effort="low",
                    function_calling_llm_model="",
                    function_calling_llm_temperature=0.0,
                    function_calling_llm_timeout=600,
                    agent_config=GLOBAL_AGENTS_CONFIG['data_checker'], # type: ignore[index]
                    agent_verbose=True,
                    agent_reasoning=False,
                    agent_max_reasoning_attempts=3,
                    agent_max_retry_limit=3,
                    task_name="data_check_task",
                    task_config=GLOBAL_TASKS_CONFIG['data_check_task'], # type: ignore[index]
                    task_expected_output=f'Final Answer MUST be a compact JSON string. Do not use pretty-printing, indentation, or newlines. No other text(like planning, description, introduction).',
                    task_output_pydantic=DataCheckResult,
                    task_converter_cls=OneChanceConverter,
                    crew_name="data_checker_crew",
                    crew_verbose=True,
                    stream=eval(os.getenv("STREAM_SWITCH","False")),
                ),
                spectific_configs=spectific_configs,
                inputs={
                    "topic": topic,
                    "original_text": original_text,
                    "extracted_data": json.dumps(extract_result),
                    "extracted_data_description": generate_model_description(ExtractionResult),
                    "knowledge": json.dumps(OUTPUT_INFOS, ensure_ascii=False),
                    "searched_data": json.dumps(search_result),
                },
                max_retry_count=max_retry_count,
                tools=tools
            )
            
            # Convert newly run results to dict
            for result_item in check_results:
                if result_item:
                    crew_name = result_item.name
                    new_check_results[crew_name] = result_item.result.pydantic.model_dump()
        else:
            print("All configured checkers already have results. Skip running.")
        
        # Merge all results (existing + newly run)
        all_check_results = {**existing_checks, **new_check_results}
        
        # Ensure every expected checker has a result
        missing_checkers = expected_checker_names - set(all_check_results.keys())
        if missing_checkers:
            raise Exception(f"Checker step failed. Missing checker results: {missing_checkers}")
        
        # Only merge checker results listed in config
        combined_check = DataCheckResult(is_pass=True, errors=[], puzzles=[])
        for crew_name in expected_checker_names:
            check_result_data = all_check_results[crew_name]
            check_result_obj = DataCheckResult.model_validate(check_result_data)
            
            if not check_result_obj.is_pass:
                combined_check.is_pass = False
            
            # Add who field on each error to identify source checker
            if check_result_obj.errors:
                for error in check_result_obj.errors:
                    error.who = crew_name
                combined_check.errors.extend(check_result_obj.errors)
            
            if check_result_obj.puzzles:
                combined_check.puzzles.extend(check_result_obj.puzzles)
        
        # Build final DataSearchCheckResult
        result_data = DataSearchCheckResult.model_validate({
            "search": search_result,
            "check": combined_check.model_dump(),
        })
        
        return CrewOutput(pydantic=result_data), new_check_results