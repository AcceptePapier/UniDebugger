import re
import logging

class NoCodeError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

def parse_code(text):
    tmp = []
    for pattern in [r'```(?:[^\n]*\n)?(.*?)```', r'```(?:[^\n]*\n)?(.*?)===', r'^(.*?)```' ,r'`(?:[^\n]*\n)?(.*?)`', r'```(?:[^\n]*\n)?(.*?)$']:
        tmp = re.findall(pattern, text, re.DOTALL)
        if len(tmp) > 0 and len(tmp[0]) > 0:
            break
    if len(tmp) == 0: #Cannot find valid code
        raise NoCodeError("Cannot extract any code from:\n@@@@@\n"+text+"\n@@@@@\n")
    return tmp

def parse_exp(text):
    tmp = []
    for pattern in [r'===(?:[^\n]*\n)?(.*?)===', r'===(?:[^\n]*\n)?(.*?)$', r'^(?:[^\n]*\n)?(.*?)```']:
        tmp = re.findall(pattern, text, re.DOTALL)
        if len(tmp) > 0: break

    if len(tmp) == 0:
        logging.warning("This response doesn't explain the repairing")
        return ""
    else:
        return "\n".join(tmp)

def remove_comment(code):
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    code = re.sub(r'//.*', '', code)
    return re.sub(r'^\s*$', '', code, flags=re.MULTILINE) #Remove empty lines

def remove_whitespace(line: str) -> str:
    return line.replace('\n', '').replace(' ', '')

def two_lines_match(line1: str, line2: str): # Match: two strings are equal ignoring comments and whitespaces
    if line1 is None or line2 is None: return False
    if line1.strip().startswith("//") and line2.strip().startswith("//"):
        line1, line2 = remove_whitespace(line1), remove_whitespace(line2)
        return len(line1) > 0 and len(line2) > 0 and line1 == line2
    line1, line2 = remove_whitespace(line1.split("//")[0]), remove_whitespace(line2.split("//")[0])
    return len(line1) > 0 and len(line2) > 0 and line1 == line2

# def insert_lists(big_list, insertions):
#     insertions.sort(key=lambda x: x[1], reverse=True)
#     for small_list, index in insertions:
#         big_list[index:index] = small_list
#     return big_list

def exist_line(line, mylst):
    if mylst is None: return True
    for l in mylst:
        if two_lines_match(l, line):
            return True
    return False

def is_valid_line(line, lenth=0):
    return len(remove_whitespace(line)) > lenth and line.strip()[0] != "+" and "missing" not in line and "buggy" not in line

def search_valid_line(lines: list[str], start_idx: int, mode, degree=1, existing=None): # Valid: Not a edited or empty line
    incre = -1 if mode == "pre" else 1
    cur_idx = start_idx + incre
    while cur_idx >= 0 and cur_idx < len(lines):
        if is_valid_line(lines[cur_idx]):
            if exist_line(lines[cur_idx], existing): 
                degree -= 1
                if degree == 0:
                    return (cur_idx, lines[cur_idx])
        cur_idx += incre
    return

def matching_with_comments(aim_line, matched, code_lines): # Perfect match: two strings are equal ignoring whitespaces
    match_perfect = []
    for match_idx in matched:
        if remove_whitespace(aim_line) == remove_whitespace(code_lines[match_idx]):
            match_perfect.append(match_idx)
    return match_perfect

def matching_lines(aim_line, code_lines, stop_at_first_match=False): # return all matched lines
    if aim_line is None: return []
    matched = []
    for idx, cl in enumerate(code_lines): 
        if two_lines_match(aim_line, cl):
            matched.append(idx)
            if stop_at_first_match: return [idx]
    return matched

def matching_neighbor(aim_codes: list[str], aim_idx: int, raw_codes: list[str], matched: list[int], existing=False, degree_limit=5) -> list[str]:
    '''
    For multiple matches, check the neighboring valid lines.
    For example: 
    We want to match a hunk of 
    for i in range(1, 10):
        print(i)
    The aim line is `print(i)` so matched is [4, 9].
        3. for i in range(1, 10):
        4.    print(i)
    vs.
        8. for i in range(5):
        9.    print(i)
    Then we check whether 3 and 8 correspond the (pre)neibor of the aim line
    Args:
        aim_codes: a short segment to be matched
        aim_idx: the to-be-matched line
        code_lines: original code lines to be matched
        matched: index in code_lines of the matched code
        existing: only check the lines both in aim_codes and code_lines
    Returns:
        Total number of lines matched with neighboring lines
    '''
    existing = raw_codes if existing else None
    pre_matched_now, post_matched_now = [m for m in matched], [m for m in matched]
    pre_also_match, post_also_match = [], []

    for degree in range(1, degree_limit+1):
        aim_pre_neibor = search_valid_line(aim_codes, aim_idx, "pre", degree=degree, existing=existing)
        aim_post_neibor = search_valid_line(aim_codes, aim_idx, "post", degree=degree, existing=existing)
        print("pre neibor", aim_pre_neibor)
        print("post neibor", aim_post_neibor)
        if aim_pre_neibor is not None:
            for match_idx in pre_matched_now:
                pre_match_neibor = search_valid_line(raw_codes, match_idx, "pre", degree=degree)
                if (pre_match_neibor is not None) and (two_lines_match(aim_pre_neibor[1], pre_match_neibor[1])):
                    pre_also_match.append(match_idx)
                if len(pre_also_match) == 1: return pre_also_match
        
        if aim_post_neibor is not None:
            for match_idx in post_matched_now:
                post_match_neibor = search_valid_line(raw_codes, match_idx, "post", degree=degree)
                if (post_match_neibor is not None) and (two_lines_match(aim_post_neibor[1], post_match_neibor[1])):
                    post_also_match.append(match_idx)
                
                if len(post_also_match) == 1: return post_also_match


        if len(pre_also_match) > 0 and len(post_also_match) > 0 and len(set(pre_also_match) & set(post_also_match)) == 1:
            return list(set(pre_also_match) & set(post_also_match))
        elif len(pre_also_match) == 0 and len(post_also_match) == 0:
            return []

        pre_matched_now, post_matched_now = [m for m in pre_also_match], [m for m in post_also_match]
        pre_also_match, post_also_match = [], []
        
    return []


def unique_matching(resp_lines, code_lines, resp_cur_idx, resp_cur_line=None, existing=False):
    resp_cur_line = resp_lines[resp_cur_idx] if resp_cur_line is None else resp_cur_line
    print("Try to match", resp_cur_line)
    matched = matching_lines(resp_cur_line, code_lines)
    if len(matched) == 1: return matched[0]
    if len(matched) == 0: return -2

    neibor_also_match = matching_neighbor(resp_lines, resp_cur_idx, code_lines, matched, degree_limit=5, existing=existing)
    if len(neibor_also_match) == 1: return neibor_also_match[0]
    print(f"fail to uniquely match '{resp_cur_line}' with {len(matched)} matches")
    return -1


if __name__ == "__main__":
    aim_line = "int g = (int) ((value - this.lowerBound) / (this.upperBound - this.lowerBound) * 255.0); // buggy line"





