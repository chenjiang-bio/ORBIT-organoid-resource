from enum import Enum
import os
import json
import tiktoken
import time
from crewai.events import BaseEventListener
from crewai.events.types.agent_events import (
    AgentExecutionStartedEvent,
    AgentExecutionCompletedEvent,
    AgentExecutionErrorEvent,
)
from crewai.events.types.tool_usage_events import (
    ToolUsageStartedEvent, 
    ToolUsageFinishedEvent, 
    ToolUsageErrorEvent
)

from ..beam.organoid_culture import PROMPT_VERSION
from .webhook_notify import send_text_message_to_notify_url

class LLMExecuteRecord:
    class LLMExecuteRecordState(str, Enum):
        UNSTARTED = "unstarted"
        RUNNING = "running"
        COMPLETED = "completed"
        ERRORED = "errored"

    def __init__(self):
        self.state = LLMExecuteRecord.LLMExecuteRecordState.UNSTARTED.value
        
    def start(self, llm_model: str, prompt_version: str, task_type:str, start_time: int, tokens_in: int, agent_metadata: dict = None):
        self.llm_model = llm_model
        self.prompt_version = prompt_version
        self.task_type = task_type
        self.start_time = start_time
        self.start_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        self.tokens_in = tokens_in
        self.state = LLMExecuteRecord.LLMExecuteRecordState.RUNNING.value
        self.metadata = agent_metadata if agent_metadata else {}

    def end(self, end_time: int, tokens_out: int):
        self.end_time = end_time
        self.end_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        self.eplapsed_time_ms = (end_time - self.start_time)*1000 # seconds to milliseconds
        self.tokens_out = tokens_out
        self.state = LLMExecuteRecord.LLMExecuteRecordState.COMPLETED.value

    def error(self, end_time: int, error: str):
        self.error_info = error
        self.end_time = end_time
        self.end_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        self.eplapsed_time_ms = (end_time - self.start_time)*1000 # seconds to milliseconds
        self.state = LLMExecuteRecord.LLMExecuteRecordState.ERRORED.value
    
    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        result = {}
        for attr in ["llm_model", "prompt_version", "task_type", "start_date", "end_date", "start_time", "end_time", "eplapsed_time_ms", "tokens_in", "tokens_out", "state", "error_info", "metadata"]:
            if hasattr(self, attr):
                result[attr] = getattr(self, attr)

        # Same task may retry multiple times; store as a list
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                try:
                    results = json.load(f)
                except Exception:
                    results = []
        else:
            results = []

        results.append(result)

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
                    

def get_tokens_estimate(model:str, task_prompt: str) -> int:
    # Estimate tokens from task_prompt (tiktoken if available, else heuristic)
    tokens_in = 0
    try:
        try:
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        tokens_in = len(enc.encode(task_prompt)) if task_prompt else 0
    except Exception:
        # Rough estimate: ~4 characters per token
        tokens_in = int(len(task_prompt) / 4) if task_prompt else 0
    finally:
        return tokens_in

class AgentLogsListener(BaseEventListener):

    def __init__(self):
        super().__init__()
        self.detail_count = 0
        self.execute_records = {}
    
    def clean(self):
        print(f"Deleting AgentLogsListener, closing {self.detail_count} open details if any.\n")
        if hasattr(self, 'log_path') and self.detail_count > 0:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                for _ in range(self.detail_count):
                    f.write("</details>\n")
        print(f"Deleting AgentLogsListener done.\n")
        
    def set_log_path(self, log_path: str):
        self.log_path = log_path
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def start(self, start_id: str):
        self.flow_id = start_id
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(f"<details><summary>GROUP: {start_id}</summary>\n\n")
        
        self.detail_count += 1
    
    def end(self, start_id: str):
        if hasattr(self, 'log_path'):
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write("</details>\n")
        self.detail_count -= 1

    def setup_listeners(self, crewai_event_bus):
        self._event_bus = crewai_event_bus  # Keep event bus reference
        
        @crewai_event_bus.on(AgentExecutionStartedEvent)
        def on_agent_started(source, event:AgentExecutionStartedEvent):
            # agent, task, tools, task_prompt
            if not hasattr(self, 'log_path'):
                print("[on_agent_started] Log path not set for AgentLogsListener.")
                return
            
            tools = [tool.name for tool in event.tools] if event.tools else []
            self.detail_count += 1
            output_str = "\n\n\n"
            output_str += f"<details><summary>{event.agent.role}: {event.task.name} with {tools}</summary>\n\n"
            output_str += "# AGENT_START    \n"
            output_str += f"- Time: {event.timestamp.isoformat()}\n"
            output_str += f"- Agent: {event.agent.role}\n"
            output_str += f"- TaskID: {event.task.id}\n"
            output_str += f"- Task: {event.task.name}\n"
            output_str += f"- Tools: {tools}\n"
            task_prompt = event.task_prompt if event.task_prompt else ""
            output_str += f"- Task Prompt: \n"
            output_str += f"```markdown\n{task_prompt}\n```\n"

            # Estimate tokens and create a record
            tokens_in = get_tokens_estimate(event.agent.llm.model, task_prompt)
            self.execute_records[event.task.id] = record = LLMExecuteRecord()
            record.start(event.agent.llm.model, PROMPT_VERSION, event.task.name, event.timestamp.timestamp(), tokens_in, agent_metadata=event.agent.fingerprint.metadata)

            send_text_message_to_notify_url(f"{event.agent.role} 🤖 starting: {event.task.name}")
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(output_str)
        
        @crewai_event_bus.on(AgentExecutionErrorEvent)
        def on_agent_execution_error(source, event:AgentExecutionErrorEvent):
            if not hasattr(self, 'log_path'):
                print("[on_agent_execution_error]Log path not set for AgentLogsListener.")
                return
            
            output_str = "\n\n\n"
            output_str += "# AGENT_ERROR    \n"
            output_str += f"- Time: {event.timestamp.isoformat()}\n"
            output_str += f"- Agent: {event.agent.role}\n"
            output_str += f"- TaskID: {event.task.id}\n"
            output_str += f"- Task: {event.task.name}\n"
            output_str += f"- Error: `{event.error}`\n"
            output_str += "</details>\n"

            record = self.execute_records.get(event.task.id)
            if record:
                record.error(event.timestamp.timestamp(), event.error)
                record.save(os.path.join(os.path.dirname(self.log_path), "records" ,f"{event.task.id}.json"))

            send_text_message_to_notify_url(f"{event.agent.role} ❌️ error: {event.task.name}  {event.error}")
            self.detail_count -= 1
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(output_str)
        
        @crewai_event_bus.on(AgentExecutionCompletedEvent)
        def on_agent_execution_completed(source, event:AgentExecutionCompletedEvent):
            if not hasattr(self, 'log_path'):
                print("[on_agent_execution_completed] Log path not set for AgentLogsListener.")
                return
            output_str = "\n\n\n"
            output_str += "# AGENT_END    \n"
            output_str += f"- Time: {event.timestamp.isoformat()}\n"
            output_str += f"- Agent: {event.agent.role}\n"
            output_str += f"- TaskID: {event.task.id}\n"
            output_str += f"- Task: {event.task.name}\n"
            output = event.output if event.output else ""
            output_str += f"- Output: \n"
            output_str += f"{output}\n"
            output_str += "</details>\n"
            self.detail_count -= 1

            send_text_message_to_notify_url(f"{event.agent.role} ✅️ completed: {event.task.name}")

            record = self.execute_records.get(event.task.id)
            if record:
                record.end(event.timestamp.timestamp(), get_tokens_estimate(event.agent.llm.model, output))
                record.save(os.path.join(os.path.dirname(self.log_path), "records" ,f"{event.task.id}.json"))
            
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(output_str)
        
        @crewai_event_bus.on(ToolUsageStartedEvent)
        def on_tool_usage_started(source, event:ToolUsageStartedEvent):
            if not hasattr(self, 'log_path'):
                print("[on_tool_usage_started] Log path not set for AgentLogsListener.")
                return
            
            output_str = "\n\n\n"
            output_str += f"<details><summary>{event.agent_role}: {event.task_name} using {event.tool_name}</summary>\n\n"
            output_str += "# TOOL_START    \n"
            output_str += f"- Time: {event.timestamp.isoformat()}\n"
            output_str += f"- Agent: {event.agent_role}\n"
            output_str += f"- TaskID: {event.task_id}\n"
            output_str += f"- Task: {event.task_name}\n"
            output_str += f"- Tool: {event.tool_name}\n"
            output_str += f"- Tool Class: {event.tool_class}\n"
            output_str += f"- Tool Args: {json.dumps(event.tool_args, indent=2, ensure_ascii=False)} \n"
            self.detail_count += 1

            send_text_message_to_notify_url(f"{event.agent_role} 🔧 tool start: {event.tool_name} task: {event.task_name}")

            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(output_str)
        
        @crewai_event_bus.on(ToolUsageErrorEvent)
        def on_tool_usage_error(source, event:ToolUsageErrorEvent):
            if not hasattr(self, 'log_path'):
                print("[on_tool_usage_error] Log path not set for AgentLogsListener.")
                return
            output_str = "\n\n\n"
            output_str += "# TOOL_ERROR    \n"
            output_str += f"- Time: {event.timestamp.isoformat()}\n"
            output_str += f"- Agent: {event.agent_role}\n"
            output_str += f"- TaskID: {event.task_id}\n"
            output_str += f"- Task: {event.task_name}\n"
            output_str += f"- Tool: {event.tool_name}\n"
            output_str += f"- Tool Class: {event.tool_class}\n"
            output_str += f"- Tool Args: {json.dumps(event.tool_args, indent=2, ensure_ascii=False)} \n"
            output_str += f"- ERROR: {event.error} \n"
            output_str += "</details>\n"
            self.detail_count -= 1

            send_text_message_to_notify_url(f"{event.agent_role} 🔧 tool error ❌️: {event.tool_name} task: {event.task_name} error: {event.error}")

            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(output_str)
        
        @crewai_event_bus.on(ToolUsageFinishedEvent)
        def on_tool_usage_finished(source, event:ToolUsageFinishedEvent):
            if not hasattr(self, 'log_path'):
                print("[on_tool_usage_finished] Log path not set for AgentLogsListener.")
                return
            output_str = "\n\n\n"
            output_str += "# TOOL_END    \n"
            output_str += f"- Time: {event.timestamp.isoformat()}\n"
            output_str += f"- Start Time: {event.started_at.isoformat()}\n"
            output_str += f"- End Time: {event.finished_at.isoformat()}\n"
            output_str += f"- Duration: {(event.finished_at - event.started_at).microseconds} ms \n"
            output_str += f"- Agent: {event.agent_role}\n"
            output_str += f"- TaskID: {event.task_id}\n"
            output_str += f"- Task: {event.task_name}\n"
            output_str += f"- Tool: {event.tool_name}\n"
            output_str += f"- Tool Class: {event.tool_class}\n"
            output_str += f"- Tool Args: {json.dumps(event.tool_args, indent=2, ensure_ascii=False)} \n"
            output_str += f"- Cache: {event.from_cache} \n"
            output_str += f"- Output: {event.output} \n"
            output_str += "</details>\n"
            self.detail_count -= 1

            send_text_message_to_notify_url(f"{event.agent_role} 🔧 tool end: {event.tool_name} task: {event.task_name}")
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(output_str)