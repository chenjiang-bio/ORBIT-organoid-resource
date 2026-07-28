from crewai import LLM, Agent, Crew, CrewOutput, Process, Task
import json
import os

from ..utils.kmllm import KMLLM
from ..utils.json_schema import SchemaWithoutDescription
from ..beam.organoid_culture import ExtractionResult, OUTPUT_INFOS, JudgementResult, DataSearchCheckResult
from ..config import GLOBAL_AGENTS_CONFIG, GLOBAL_TASKS_CONFIG
from .crew_utils import crew_kickoff, OneChanceConverter

from crewai.tools import BaseTool
from crewai_tools.adapters.tool_collection import ToolCollection
from crewai.utilities.converter import generate_model_description

class CrewDataJudger():
    def run(self, work_name:str, topic:str, original_text:str, judger_content:str, search_check_dict:dict, max_retry_count=3, tools:ToolCollection[BaseTool]=None) -> CrewOutput:
        judger = Agent(
            config=GLOBAL_AGENTS_CONFIG['judger'], # type: ignore[index]
            verbose=True,
            llm=LLM(
                model=os.getenv("JUDGE_API_MODEL"),
                temperature=float(os.getenv("JUDGE_API_TEMPERATURE")),
                timeout=int(os.getenv("JUDGE_API_TIMEOUT")),
                reasoning_effort=os.getenv("JUDGE_API_REASONING_EFFORT"),
                base_url=os.getenv("JUDGE_API_BASEURL"),
                api_key=os.getenv("JUDGE_API_KEY"),
                num_ctx=int(os.getenv("JUDGE_NUM_CTX", 262144)),
                stream=eval(os.getenv("STREAM_SWITCH","False")),
            ),
            reasoning=False,   
        )
        judger.security_config.fingerprint.metadata = {
            "work_name": work_name
        }
        judge_task = Task(
            name="judge_task",
            config=GLOBAL_TASKS_CONFIG['judge_task'], # type: ignore[index]
            expected_output=f'Final Answer MUST be a compact JSON string. Do not use pretty-printing, indentation, or newlines. No other text(like planning, description, introduction).',
            output_pydantic=JudgementResult,
            agent=judger,
            converter_cls=OneChanceConverter,
        )

        judger_crew = Crew(
            name="judger_crew",
            agents=[judger],
            tasks=[judge_task],
            process=Process.sequential,
            verbose=True,
        )
        result = crew_kickoff(judger_crew, inputs={
            "topic": topic,
            "original_text": original_text,
            "knowledge": json.dumps(OUTPUT_INFOS, ensure_ascii=False),
            "waiting_for_scores": judger_content,
            "extracted_data_description": generate_model_description(ExtractionResult),
            "checked_data": json.dumps(search_check_dict),
            "checked_data_description": generate_model_description(DataSearchCheckResult),      

        }, max_retry_count=max_retry_count)
        return result
