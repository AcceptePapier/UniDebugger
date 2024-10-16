import javalang
from apted import APTED, Config

def code2ast(code):
    return javalang.parse.parse(code)

def ast_to_tuple(node):
    if isinstance(node, javalang.ast.Node):
        children = [ast_to_tuple(child) for _, child in node.children() if isinstance(child, javalang.ast.Node)]
        return (node.__class__.__name__, children)
    return None

def ast_dis(tree1: javalang.ast.Node, tree2: javalang.ast.Node):
    tuple1, tuple2 = ast_to_tuple(tree1), ast_to_tuple(tree2)
    apted = APTED(tuple1, tuple2)
    return apted.compute()

    
