from crewai import CrewOutput
import json
import os

from ..utils.json_schema import SchemaWithoutDescription
from ..beam.organoid_culture import ExtractionResult, OUTPUT_INFOS, DataSearchCheckResult
from ..config import GLOBAL_AGENTS_CONFIG, GLOBAL_TASKS_CONFIG
from .crew_utils import parallel_crew, ParallelCrewConfig, OneChanceConverter

from crewai.utilities.converter import generate_model_description
from crewai.tools import BaseTool
from crewai_tools.adapters.tool_collection import ToolCollection


class CrewDataCorrectors():
    async def run(self, work_name:str, topic:str, original_text:str, extract_result:dict, search_check_dict:dict, exists_result:set, max_retry_count:int=3, tools:ToolCollection[BaseTool]=None) -> CrewOutput:
        
        init_spectific_configs = [
            {
                "llm_model":os.getenv("CORRECT_API_MODEL1"),
                "task_name":os.getenv("CORRECT_API_NAME1"),
                "crew_name":os.getenv("CORRECT_API_NAME1"),
                "llm_api_key": os.getenv("CORRECT_API_KEY1"),
                "llm_base_url": os.getenv("CORRECT_API_BASEURL1"),
                "llm_temperature": float(os.getenv("CORRECT_API_TEMPERATURE")),
                "llm_timeout": int(os.getenv("CORRECT_API_TIMEOUT")),
                "llm_reasoning_effort": os.getenv("CORRECT_API_REASONING_EFFORT"),
                "llm_num_ctx": int(os.getenv("CORRECT_NUM_CTX", 262144)),
            },   
            {
                "llm_model":os.getenv("CORRECT_API_MODEL2"),
                "task_name":os.getenv("CORRECT_API_NAME2"),
                "crew_name":os.getenv("CORRECT_API_NAME2"),
                "llm_api_key": os.getenv("CORRECT_API_KEY2"),
                "llm_base_url": os.getenv("CORRECT_API_BASEURL2"),
                "llm_temperature": float(os.getenv("CORRECT_API_TEMPERATURE")),
                "llm_timeout": int(os.getenv("CORRECT_API_TIMEOUT")),
                "llm_reasoning_effort": os.getenv("CORRECT_API_REASONING_EFFORT"),
                "llm_num_ctx": int(os.getenv("CORRECT_NUM_CTX", 262144)),
            },
        ]
        spectific_configs = []
        for spectific_config in init_spectific_configs:
            if spectific_config["crew_name"] not in exists_result:
                spectific_configs.append(spectific_config)
        
        if len(spectific_configs) == 0:
            return

        final_output_results = await parallel_crew(
            template_agent_config=ParallelCrewConfig(
                work_name=work_name,
                llm_model="",
                llm_temperature=0.0,
                llm_timeout=600,
                llm_reasoning_effort="low",
                llm_num_ctx=1048576,
                function_calling_llm_model="",
                function_calling_llm_temperature=0.0,
                function_calling_llm_timeout=600,
                # function_calling_llm_real_provider="xai",
                agent_config=GLOBAL_AGENTS_CONFIG['corrector'], # type: ignore[index]
                agent_verbose=True,
                agent_reasoning=False,
                agent_max_reasoning_attempts=3,
                agent_max_retry_limit=3,
                task_name="correct_task",
                task_config=GLOBAL_TASKS_CONFIG['correct_task'], # type: ignore[index]
                task_expected_output="Final answer MUST be a formatted and **completed** and human-readable JSON string: use 2-space indentation; place each object and array element on its own line with proper alignment. Do NOT output compact single-line JSON. Do NOT output any text outside the JSON (no planning, explanation, description, or comments). ",
                task_output_pydantic=ExtractionResult,
                task_converter_cls=OneChanceConverter,
                crew_name="correct_crew",
                crew_verbose=True,
                stream=eval(os.getenv("STREAM_SWITCH","False")),
            ),
            spectific_configs=spectific_configs,
            inputs={
                "topic":topic,
                "original_text": original_text,
                "extracted_data": json.dumps(extract_result),
                "extracted_data_description": "`Same as the final answer JSON schema`",
                "checked_data": json.dumps(search_check_dict),
                "checked_data_description": generate_model_description(DataSearchCheckResult),
                "knowledge": json.dumps(OUTPUT_INFOS, ensure_ascii=False)
            },
            max_retry_count=max_retry_count,
            # tools=tools
        )
        return final_output_results