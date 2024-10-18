import os
from retry import retry
import logging
from utils import read_yaml
from agents.agent import Agent, RetryError
from prompts.tokens import *
from tavily import TavilyClient
import json


def tavily_search(query):
    tavily_env = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tavily_env.yaml"))
    tavily_client = TavilyClient(api_key=tavily_env["api_key"])
    return tavily_client.get_search_context(query, search_depth="advanced", max_tokens=8000)
        
class Helper(Agent):
    def parse_response(self, response: str):
        match = re.search(r"(.*?)===\s*(.*?)\s*===", response, re.DOTALL)
        if match:
            return {"ori": response, "aim": match.group(1).strip(), "exp": match.group(2).strip()}
        else:
            raise RetryError(response)   

    def __generate_core_msg(self, info):
        self.core_msg = "The following code contains a bug:\n" + info['buggy_code']
        self.__shared_msg(info)

    @retry((RetryError), tries=3, delay=5)
    def run(self, info: dict, max_tries=10, *args):
        logging.info("## Running Helper...")
        self.prompts_dict = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/helper.yaml"))
        if self.core_msg is None:
            self.__generate_core_msg(info)
        
        tools =[{"type": "function",
                "function": {
                    "name": "tavily_search",
                    "description": "Get related solutions to fix the bug from the web.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The search query to use. A sentence describing the error in the code with the limit of 100 words."},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    }
                }
        }]
        for _ in range(max_tries):
            response = self.send_message(
                    msg = [{"role": "system", "content": self.prompts_dict["sys"]},
                           {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]},
                    ],
                    tools=tools,
                    handling=False
            )
            if response.choices[0].finish_reason == "tool_calls":
                arguments = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
                logging.info("## Query: " +arguments.get("query"))
                context = tavily_search(arguments.get("query"))
                return self.parse_response(self.send_message(
                    msg = [{"role": "system", "content": self.prompts_dict["sys"]},
                           {"role": "user", "content": self.core_msg + "\n" + self.prompts_dict["end"]},
                           response.choices[0].message,
                           {"role": "tool", "content": json.dumps({"query": arguments.get("query"), "tavily_search_result": context}),
                            "tool_call_id": response.choices[0].message.tool_calls[0].id}
                    ]
                ))


    
   