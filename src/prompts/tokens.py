from parse import *

token_limit = {
    "gpt-4o-2024-08-06": {"buggy_code": 8000, "failing_test_cases": 1000, "summary": 5120, "overall": 30000},
    "gpt-4o-mini": {"buggy_code": 8000, "failing_test_cases": 1000, "summary": 5120, "overall": 30000},
    "gpt-4o": {"buggy_code": 8000, "failing_test_cases": 1000, "summary": 5120, "overall": 30000},
    "deepseek-coder": {"buggy_code": 8000, "failing_test_cases": 1000, "summary": 5120, "overall": 12800},
    "gpt-3.5-turbo-ca": {"buggy_code": 8000, "failing_test_cases": 1000, "summary": 1000, "overall": 12800},
    "gemini-1.5-flash": {"buggy_code": 8000, "failing_test_cases": 1000, "summary": 5120, "overall": 12800},
    "claude-3-5-sonnet-20240620": {"buggy_code": 8000, "failing_test_cases": 1000, "summary": 5120, "overall": 12800},

}

def calculate_token(*args):
    lenth = 0
    for v in args:
        if isinstance(v, int):
            lenth += v * 2
        elif isinstance(v, str):
            lenth += len(v)
        elif isinstance(v, list) and isinstance(v[0], dict):
            lenth += sum([len(vd["content"]) for vd in v])
    return lenth // 4

def shorten(ori_text:str, aim_token:int, coverage=list[int]):
    if calculate_token(ori_text) <= aim_token:
        return ori_text
    ori_lenth = len(ori_text)
    print("Cutting from", calculate_token(ori_text))
    
    text = remove_comment(ori_text)
    print("1st shorten: remove comments...", ori_lenth, "->", len(text))

    if calculate_token(text) > aim_token:
        tmp = []
        for line in text.splitlines():
            if not line.startswith("import") or len(line.strip()) < 1:
                tmp.append(line.strip())
        text = "\n".join(tmp)
        print("2nd shorten: remove packages...", ori_lenth, "->", len(text))
    
    if calculate_token(text) > aim_token:
        if len(coverage) > 0:
            s, e = min(coverage), max(coverage)
            text = remove_comment("\n".join(ori_text.splitlines()[s-1: e]))
        print("3rd only keep executed code...", ori_lenth, "->", len(text))
    
    return text