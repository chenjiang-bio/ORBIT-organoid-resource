from crewai import LLM, Agent, Crew, CrewOutput, Process, Task
import json

from ..utils.kmllm import KMLLM
from ..utils.json_schema import SchemaWithoutDescription
from ..beam.organoid_culture import ExtractionResult, OUTPUT_INFOS, DataSearchResult, DataSearchPlan
from ..config import GLOBAL_AGENTS_CONFIG, GLOBAL_TASKS_CONFIG
from .crew_utils import crew_kickoff, OneChanceConverter

from crewai.utilities.converter import generate_model_description
from crewai.tools import BaseTool
from crewai_tools.adapters.tool_collection import ToolCollection
import os
 


class CrewDataSearcherPlan():
    """Phase 1: Plan generation for search workflow
    
    Analyzes EXTRACTED_DATA/ORIGINAL_TEXT → generates DataSearchPlan
    No tools required in this phase.
    """
    
    def run(
        self, 
        work_name: str, 
        topic: str, 
        original_text: str, 
        extract_result: dict, 
        max_retry_count: int = 3
    ) -> CrewOutput:
        """
        Execute Phase 1: Generate search plan.
        
        Args:
            work_name: Identifier for tracking this workflow execution
            topic: Domain topic (e.g., "Organoid")
            original_text: Source paper text
            extract_result: ExtractionResult dict
            max_retry_count: Retry limit for plan generation (default: 3)
        
        Returns:
            CrewOutput containing DataSearchPlan
        """
        
        # ========== PHASE 1: PLANNER (No tools, generates DataSearchPlan) ==========
        planner = Agent(
            config=GLOBAL_AGENTS_CONFIG['data_search_planner'],  # type: ignore[index]
            verbose=True,
            llm=LLM(
                model=os.getenv("SEARCH_PLAN_API_MODEL"),
                temperature=float(os.getenv("SEARCH_PLAN_API_TEMPERATURE")),
                timeout=int(os.getenv("SEARCH_PLAN_API_TIMEOUT")),
                reasoning_effort=os.getenv("SEARCH_PLAN_API_REASONING_EFFORT"),
                base_url=os.getenv("SEARCH_PLAN_API_BASEURL"),
                api_key=os.getenv("SEARCH_PLAN_API_KEY"),
                num_ctx=int(os.getenv("SEARCH_PLAN_NUM_CTX", 262144)),
                stream=eval(os.getenv("STREAM_SWITCH","False")),
            ),
            max_rpm=3,
            tools=None,  # Planner does NOT use tools
            reasoning=False,
        )
        planner.security_config.fingerprint.metadata = {
            "work_name": work_name,
        }
        
        plan_task = Task(
            name="data_search_plan_task",
            config=GLOBAL_TASKS_CONFIG['data_search_plan_task'],  # type: ignore[index]
            expected_output=(
                "Final Answer MUST be a compact JSON string. Do not use pretty-printing, indentation, or newlines. No other text (like planning, description, introduction)."
            ),
            output_pydantic=DataSearchPlan,
            agent=planner,
            converter_cls=OneChanceConverter,
        )
        
        planner_crew = Crew(
            name="data_search_planner_crew",
            agents=[planner],
            tasks=[plan_task],
            process=Process.sequential,
            verbose=True,
        )
        
        # Execute Phase 1: Generate search plan
        plan_output = crew_kickoff(
            planner_crew, 
            inputs={
                "topic": topic,
                "original_text": original_text,
                "extracted_data": json.dumps(extract_result),
                "extracted_data_description": generate_model_description(ExtractionResult),
                "knowledge": json.dumps(OUTPUT_INFOS, ensure_ascii=False)
            }, 
            max_retry_count=max_retry_count
        )

        return plan_output


class CrewDataSearcherExecute():
    """Phase 2: Execute search plan with tools
    
    Executes DataSearchPlan with tools → produces DataSearchResult
    """
    
    def run(
        self, 
        work_name: str, 
        topic: str, 
        search_plan: dict | DataSearchPlan, 
        max_retry_count: int = 3, 
        tools: ToolCollection[BaseTool] = None
    ) -> CrewOutput:
        """
        Execute Phase 2: Execute search plan with tools.
        
        Args:
            work_name: Identifier for tracking this workflow execution
            topic: Domain topic (e.g., "Organoid")
            search_plan: DataSearchPlan from Phase 1 (dict or Pydantic model)
            max_retry_count: Retry limit for execution (default: 3)
            tools: Tool collection for search operations
        
        Returns:
            CrewOutput containing final DataSearchResult
        """
        
        # ========== PHASE 2: EXECUTOR (Uses tools, executes DataSearchPlan) ==========
        executor = Agent(
            config=GLOBAL_AGENTS_CONFIG['data_search_executor'],  # type: ignore[index]
            verbose=True,
            llm=LLM(
                model=os.getenv("SEARCH_EXECUTE_API_MODEL"),
                temperature=float(os.getenv("SEARCH_EXECUTE_API_TEMPERATURE")),
                timeout=int(os.getenv("SEARCH_EXECUTE_API_TIMEOUT")),
                reasoning_effort=os.getenv("SEARCH_EXECUTE_API_REASONING_EFFORT"),
                num_ctx=int(os.getenv("SEARCH_EXECUTE_NUM_CTX", 262144)),
                base_url=os.getenv("SEARCH_EXECUTE_API_BASEURL"),
                api_key=os.getenv("SEARCH_EXECUTE_API_KEY"),
                stream=eval(os.getenv("STREAM_SWITCH","False")),
            ),
            # max_rpm=3,
            tools=tools,  # Executor uses ALL search tools
            reasoning=False,
            max_iter=100,  # Executor may need many tool calls
        )
        executor.security_config.fingerprint.metadata = {
            "work_name": work_name,
        }
        
        execute_task = Task(
            name="data_search_execute_task",
            config=GLOBAL_TASKS_CONFIG['data_search_execute_task'],  # type: ignore[index]
            expected_output=(
                "FINAL OUTPUT: **ONLY DataSearchResult** (containing all searching records). "
                "Final Answer MUST be a compact JSON string. Do not use pretty-printing, indentation, or newlines. "
                "No other text (like planning, description, introduction)."
            ),
            output_pydantic=DataSearchResult,
            agent=executor,
            converter_cls=OneChanceConverter,
        )
        
        executor_crew = Crew(
            name="data_search_executor_crew",
            agents=[executor],
            tasks=[execute_task],
            process=Process.sequential,
            verbose=True,
        )
        
        # Execute Phase 2: Execute search plan with tools
        executor_retry_count = 0
        max_executor_retries = max_retry_count
        
        while executor_retry_count <= max_executor_retries:
            search_result = crew_kickoff(
                executor_crew, 
                inputs={
                    "topic": topic,
                    "search_plan": json.dumps(search_plan, ensure_ascii=False) if isinstance(search_plan, dict) else search_plan.model_dump_json(),
                    "search_plan_description": generate_model_description(DataSearchPlan),
                }, 
                max_retry_count=max_retry_count
            )
            
            # Validate: Executor must produce same n_querys as Planner
            plan_n_querys = search_plan.n_querys if hasattr(search_plan, 'n_querys') else search_plan['n_querys']
            
            # Extract result n_querys
            result_n_querys = search_result.pydantic.n_querys
            
            # Check consistency
            if result_n_querys >= plan_n_querys:
                print(f"✓ Executor validation passed: n_querys matched ({result_n_querys} >= {plan_n_querys})")
                break
            else:
                executor_retry_count += 1
                print(f"⚠️  Executor validation failed: n_querys mismatch ({result_n_querys} < {plan_n_querys})")
                
                if executor_retry_count <= max_executor_retries:
                    print(f"🔄 Retrying Executor (attempt {executor_retry_count}/{max_executor_retries})...")
                    # Optionally: add error context to next attempt
                    executor_crew.tasks[0].description += (
                        f"\n\n**PREVIOUS ATTEMPT ERROR**: You returned {result_n_querys} searches but plan requires {plan_n_querys}. "
                        f"Ensure you create EXACTLY {plan_n_querys} DataSearchInfo records."
                    )
                else:
                    # Final attempt failed
                    raise ValueError(
                        f"Executor failed after {max_executor_retries} retries: "
                        f"n_querys mismatch ({result_n_querys} != {plan_n_querys}). "
                        f"Planner expected {plan_n_querys} searches but Executor returned {result_n_querys}."
                    )

        return search_result