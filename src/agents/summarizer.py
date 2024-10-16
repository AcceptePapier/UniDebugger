import os
from retry import retry
from utils import read_yaml
from agents.agent import Agent, RetryError
from prompts.tokens import *
from collections import defaultdict


class Summarizer(Agent):

    def parse_response(self, response: str):
        result = defaultdict(dict)
        for line in response.splitlines():
            parts = [a for a in line.split("~") if len(a.strip()) > 0]
            if not (len(parts) == 5): 
                logging.warning(f"Not meet the format need: {line}")
                if len(parts) >= 3:
                    result[parts[0][1:-1]][parts[1][1:-1]] = "\t".join([p[1:-1] for p in parts[2:]])
                    continue
                else:
                    print(line); continue
            class_name, func_name, return_type, desp = parts[0][1:-1], parts[1][1:-1], parts[-2][1:-1], parts[-1][1:-1]
            if len(parts[2]) > 0:
                try:
                    parameters = {param.split(":")[0].strip(): param.split(":")[1].strip() for param in parts[2][1:-1].split(",")}
                except:
                    parameters = parts[2][1:-1].split(",")
            else:
                parameters = {}
            
            result[class_name][func_name] = {"paras": parameters, "return_type": return_type, "desp": desp}

        if len(result) == 0:
            raise RetryError("No valid parts!")
        return {"aim": result, "exp": "", "ori": response}

    @retry((RetryError), tries=3, delay=5)
    def run(self, code):
        logging.info("## Running Summarizer...")
        self.prompts_dict = read_yaml(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../prompts/summarizer.yaml"))
        
        return self.parse_response(self.send_message([
                {"role": "system", "content": self.prompts_dict["sys"]},
                {"role": "user", "content": "Raw Code:\n" + code + "\n" + self.prompts_dict["end"]}])
        )
