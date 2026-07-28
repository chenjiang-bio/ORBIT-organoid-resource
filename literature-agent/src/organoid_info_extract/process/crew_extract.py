from crewai import LLM, Agent, Crew, CrewOutput, Process, Task
import json
import os

from ..utils.json_schema import SchemaWithoutDescription
from ..beam.organoid_culture import ExtractionResult, OUTPUT_INFOS
from ..config import GLOBAL_AGENTS_CONFIG, GLOBAL_TASKS_CONFIG
from .crew_utils import crew_kickoff, OneChanceConverter

from crewai.tools import BaseTool
from crewai_tools.adapters.tool_collection import ToolCollection

class CrewDataExtractor():
    def run(self, work_name:str, topic:str, original_text:str, max_retry_count:int=3, tools:ToolCollection[BaseTool]=None) -> CrewOutput:
        extrator = Agent(
            config=GLOBAL_AGENTS_CONFIG['extractor'], # type: ignore[index]
            verbose=True,
            llm=LLM(
                model=os.getenv("EXTRACT_API_MODEL"),
                temperature=float(os.getenv("EXTRACT_API_TEMPERATURE")),
                timeout=int(os.getenv("EXTRACT_API_TIMEOUT")),
                reasoning_effort=os.getenv("EXTRACT_API_REASONING_EFFORT"),
                base_url=os.getenv("EXTRACT_API_BASEURL"),
                api_key=os.getenv("EXTRACT_API_KEY"),
                num_ctx=int(os.getenv("EXTRACT_NUM_CTX", 262144)),
                stream=eval(os.getenv("STREAM_SWITCH","False")),
            ),
            reasoning=False,    
            # tools=tools,  # Extractor should NOT use external tools per agents.yaml definition
        )
        extrator.security_config.fingerprint.metadata = {
            "work_name": work_name
        }
        extract_task = Task(
            name="extract_task",
            config=GLOBAL_TASKS_CONFIG['extract_task'], # type: ignore[index]
            expected_output=f'Final Answer must strictly extract the data into the requested JSON schema. Do not ask clarifying questions. Do not summarize the text. Output only the completed and structured data directly. If the text implies multiple entries, merge them into one comprehensive object or pick the most relevant one.',
            output_pydantic=ExtractionResult,
            converter_cls=OneChanceConverter,
            agent=extrator,
        )

        extractor_crew = Crew(
            name="extractor_crew",
            agents=[extrator],
            tasks=[extract_task],
            process=Process.sequential,
            verbose=True,
        )
        result = crew_kickoff(extractor_crew, inputs={
            "topic": topic,
            "original_text": original_text,
            "knowledge": json.dumps(OUTPUT_INFOS, ensure_ascii=False)
        }, max_retry_count=max_retry_count)

        return result