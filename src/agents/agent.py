from abc import ABC, abstractmethod
import openai
import google.generativeai as genai
import logging
from retry import retry
from utils import read_json
from prompts.tokens import *

class RetryError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class Agent(ABC):
    def __init__(self, model_name, hash_id, config_path="../config.json") -> None:
        self.model_name = model_name
        self.hash_id = hash_id
        self.client = self.set_client(config_path)
        self.core_msg = None
    
    def __str__(self):
        return self.__class__.__name__

    def __repr__(self):
        return self.__str__()
    
    def __print_msg(self, msg):
        print("#"*30)
        for lst in msg:
            print("#", len(lst["content"])//2, lst["content"].split('\n')[0].split('.')[0])   
        print("#"*30)
    
    def set_client(self, config_path):
        config = read_json(config_path)
        if self.model_name.startswith("gpt") or self.model_name.startswith("claude"):
            return openai.OpenAI(
                base_url="https://api.chatanywhere.tech/v1",                                                                                                            
                api_key=config["ChatGPT"]
            )
        if self.model_name.startswith("deepseek"):
            return openai.OpenAI(
                base_url="https://api.deepseek.com/v1",
                api_key=config["DeepSeek"]
            )
        if self.model_name.startswith("Phind"):
            return openai.OpenAI(
                base_url="https://api.deepinfra.com/v1/openai",
                api_key=config["DeepInfra"]
            )
        if self.model_name.startswith("gemini"):
            genai.configure(api_key=config["Gemini"])
            return genai.GenerativeModel(self.model_name,
                                         safety_settings=[
                                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                                    ]
            )
    

    def __handle_response(self, response): # Do not consider tool use
        status_code = response.choices[0].finish_reason
        print("="*50, status_code)
        print(response.choices[0].message.content)
        print("="*50)
        
        if status_code == "stop":
            return response.choices[0].message.content
        elif status_code == "length":
            logging.warning(f"The response is not completed with {len(response.choices[0].message.content)} output tokens!")
            return response.choices[0].message.content
        elif status_code == "tool_calls":
            return response
        elif status_code == "content_filter":
            logging.warning("Input contains risky contents!")
            return None
        else:
            logging.warning(f"LLM returns\n"+response.choices[0].message.content)
            raise RetryError("try again") 

    def __handle_gemini_response(self, response):
        status_code = response.candidates[0].finish_reason._name_
        print("="*50, status_code)
        print(response.text)
        print("="*50)

        if status_code == "STOP":
            return response.text
        else:
            return response

    def __dict_prompt_to_text(self, msg: list[dict]):
        return "\n".join([dct["content"] for dct in msg])
    
    def __shared_msg(self, info={}, pre_agent_resp={}):
        self.core_msg += "\nThe code fails on this test:\n" + info["failing_test_cases"]

        if "summarizer" in pre_agent_resp and calculate_token(self.core_msg + pre_agent_resp["summarizer"]) <= token_limit[self.model_name]["overall"]:
            self.core_msg = "Related code summary:\n" + pre_agent_resp["summarizer"] + "\n" + self.core_msg
        if "helper" in pre_agent_resp and calculate_token(self.core_msg + pre_agent_resp["helper"]) <= token_limit[self.model_name]["overall"]:
            self.core_msg = "Reference debugging guide:\n" + pre_agent_resp["helper"] + "\n" + self.core_msg


    @retry((openai.APIConnectionError, openai.Timeout, openai.APITimeoutError, RetryError), tries=3, delay=2, backoff=2)
    def send_message(self, msg: list[dict], tools=[], handling=True):
        if "gemini" not in self.model_name:
            if len(tools) > 0:
                response = self.client.chat.completions.create(model=self.model_name, messages=msg, tools=tools)
            else: response = self.client.chat.completions.create(model=self.model_name, messages=msg)
            if handling: return self.__handle_response(response)
            else: return response
            
        else: # Not tool use
            response = self.client.generate_content(self.__dict_prompt_to_text(msg))
            if handling: return self.__handle_gemini_response(response)
            else: return response

    @abstractmethod
    def parse_response(self, response: str, *args):
        pass

    @abstractmethod
    def run(self, info: dict, *args):
        pass




