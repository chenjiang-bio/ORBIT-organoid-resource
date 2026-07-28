
import asyncio
from crewai import LLM, Agent, Crew, CrewOutput, Process, Task
from pydantic import BaseModel, Field
from typing import List, TYPE_CHECKING

from crewai.tools import BaseTool
from crewai_tools.adapters.tool_collection import ToolCollection
from ..utils.kmllm import KMLLM

from json import JSONDecodeError
from pydantic import ValidationError
from crewai.utilities.converter import Converter, CrewValidationError

if TYPE_CHECKING:
    from crewai.utilities.internal_instructor import InternalInstructor

class OneChanceConverter(Converter):
    """Custom Converter that forces JSON mode instead of TOOLS mode to avoid instructor multiple-tool-calls errors."""
    max_attempts: int = Field(
        description="Max number of attempts to try to get the output formatted.",
        default=0,
    )
    
    def _create_instructor(self) -> "InternalInstructor":
        """Override parent to create an instructor client in JSON mode."""
        from crewai.utilities.internal_instructor import InternalInstructor
        from crewai.utilities.logger_utils import suppress_warnings
        
        # Create base instructor instance
        instructor_instance = InternalInstructor(
            llm=self.llm,
            model=self.model,
            content=self.text,
        )
        
        # Patch instructor client to force JSON mode
        with suppress_warnings():
            import instructor
            from litellm import completion
            
            # Use JSON mode instead of default TOOLS mode
            instructor_instance._client = instructor.from_litellm(
                completion,
                mode=instructor.Mode.JSON  # Force JSON mode
            )
        
        return instructor_instance


class CrewOutputWithName:
    def __init__(self, name:str, result:CrewOutput):
        self.name = name
        self.result = result

async def crew_kickoff_async(crew, inputs: dict, max_retry_count=3) -> CrewOutputWithName | None:
    n_retry = max_retry_count
    inputs_copy = inputs.copy()
    inputs_copy['last_error'] = ""
    inputs_copy['last_output'] = ""
    result = None
    while n_retry > 0:
        try:
            n_retry -= 1
            result = await crew.kickoff_async(inputs=inputs_copy) # result: CrewOutput
            if result:
                return CrewOutputWithName(name=crew.name, result=result)
            else:
                print(f"Crew kickoff_async returned no result. Retries left: {n_retry}")
                continue
        except KeyboardInterrupt as kie:
            raise kie
        except CrewValidationError as cve:
            print(f"Validation Error during crew kickoff_async, Retries left: {n_retry} Error: {cve}")
            inputs_copy['last_error'] = cve.msg
            inputs_copy['last_output'] = cve.result
            continue
        except Exception as e:
            print(f"Error during crew kickoff_async, Retries left: {n_retry} Error: {e}")
            inputs_copy['last_error'] = str(e)
            inputs_copy['last_output'] = result.raw if result else "The result has been not be read."
            continue
    return None



class ParallelCrewConfig(BaseModel):
    work_name:str
    llm_model:str
    llm_temperature:float
    llm_timeout:int
    llm_reasoning_effort:str
    llm_frequency_penalty:float | None = None
    llm_base_url:str | None = None
    llm_api_key:str | None = None
    llm_response_format:dict | None = None
    llm_num_ctx:int | None = None
    stream:bool = False
    function_calling_llm_model:str
    function_calling_llm_temperature:float
    function_calling_llm_timeout:int
    function_calling_llm_real_provider:str | None = None
    function_calling_llm_base_url:str | None = None
    function_calling_llm_api_key:str | None = None
    agent_config:dict
    agent_verbose:bool
    agent_reasoning:bool
    agent_max_reasoning_attempts:int
    agent_max_retry_limit:int
    task_name:str
    task_config:dict
    task_expected_output:str
    task_output_pydantic:type[BaseModel]
    task_converter_cls:type[Converter] | None = None
    crew_name:str
    crew_verbose:bool

def crew_kickoff(crew, inputs: dict, max_retry_count=3) -> CrewOutput:
    n_retry = max_retry_count
    inputs_copy = inputs.copy()
    inputs_copy['last_error'] = ""
    inputs_copy['last_output'] = ""
    result = None
    while n_retry > 0:
        try:
            n_retry -= 1
            result = crew.kickoff(inputs=inputs_copy)
            if result:
                return result
            else:
                print(f"Crew kickoff returned no result. Retries left: {n_retry}")
                continue
        except KeyboardInterrupt as kie:
            raise kie
        except CrewValidationError as cve:
            print(f"Validation Error during crew kickoff, Retries left: {n_retry} Error: {cve}")
            inputs_copy['last_error'] = cve.msg
            inputs_copy['last_output'] = cve.result
            continue
        except Exception as e:
            print(f"Error during crew kickoff, Retries left: {n_retry} Error: {e}")
            inputs_copy['last_error'] = str(e)
            inputs_copy['last_output'] = result.raw if result else "The result has been not be read."
            continue
    return None


def crews_kickoff(crews, inputs: dict, max_retry_count=3) -> CrewOutput:
    n_retry = max_retry_count
    inputs_copy = inputs.copy()
    inputs_copy['last_error'] = ""
    inputs_copy['last_output'] = ""
    result = None
    while n_retry > 0:
        try:
            crew: Crew = crews[(max_retry_count-n_retry) % len(crews)]
            n_retry -= 1
            print(f"Starting kickoff for crew: {crew.name}, llm:{crew.agents[0].llm.model},Retries left: {n_retry}")
            result = crew.kickoff(inputs=inputs_copy)
            if result:
                return result
            else:
                inputs_copy['last_error'] = "No Response."
                inputs_copy['last_output'] = ""
                print(f"Crew kickoff returned no result. Retries left: {n_retry}")
                continue
        except KeyboardInterrupt as kie:
            raise kie
        except CrewValidationError as cve:
            print(f"Validation Error during crew kickoff, Retries left: {n_retry} Error: {cve}")
            inputs_copy['last_error'] = cve.msg
            inputs_copy['last_output'] = cve.result
            continue
        except Exception as e:
            print(f"Error during crew kickoff, Retries left: {n_retry} Error: {e}")
            inputs_copy['last_error'] = str(e)
            inputs_copy['last_output'] = result.raw if result else "The result has been not be read."
            continue
    return None

async def parallel_crew(template_agent_config:ParallelCrewConfig, spectific_configs:List[dict], inputs:dict, max_retry_count:int=3, tools:ToolCollection[BaseTool]=None) -> List[CrewOutputWithName]:
    crews = []

    for spec_config_dict in spectific_configs:
        spec_config = template_agent_config.model_copy(update=spec_config_dict)
        if spec_config.function_calling_llm_model and spec_config.function_calling_llm_model.strip() != "":
            function_calling_llm = KMLLM(
                model=spec_config.function_calling_llm_model,
                temperature=spec_config.function_calling_llm_temperature,
                timeout=spec_config.function_calling_llm_timeout,
                real_provider=spec_config.function_calling_llm_real_provider,
                base_url=spec_config.function_calling_llm_base_url,
                api_key=spec_config.function_calling_llm_api_key
            )
        else:
            function_calling_llm = None
        agent = Agent(
            config=spec_config.agent_config, # type: ignore[index]
            verbose=spec_config.agent_verbose,
            llm=LLM(
                model=spec_config.llm_model,
                temperature=spec_config.llm_temperature,
                timeout=spec_config.llm_timeout,
                reasoning_effort=spec_config.llm_reasoning_effort,
                base_url=spec_config.llm_base_url,
                api_key=spec_config.llm_api_key,
                stream=spec_config.stream,
                frequency_penalty=spec_config.llm_frequency_penalty,
                response_format=spec_config.llm_response_format,
                num_ctx=spec_config.llm_num_ctx,
            ),
            function_calling_llm=function_calling_llm,
            reasoning=spec_config.agent_reasoning,
            max_reasoning_attempts=spec_config.agent_max_reasoning_attempts,
            max_retry_limit=spec_config.agent_max_retry_limit,
            tools=tools,
        )
        agent.security_config.fingerprint.metadata = {
            "work_name": spec_config.work_name
        }
        task = Task(
            name=spec_config.task_name,
            config=spec_config.task_config,
            expected_output=spec_config.task_expected_output,
            output_pydantic=spec_config.task_output_pydantic,
            converter_cls=spec_config.task_converter_cls,
            agent=agent
        )

        crew = Crew(
            name=spec_config.crew_name,
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=spec_config.crew_verbose,
        )
        crews.append(crew)

    # Kickoff all crews in parallel
    results = []
    for crew_obj in crews:
        check_result = crew_kickoff_async(crew_obj, inputs=inputs, max_retry_count=max_retry_count)
        if check_result:
            results.append(check_result)
    
    # Await the results using asyncio.gather
    results = await asyncio.gather(*results)

    return results
       