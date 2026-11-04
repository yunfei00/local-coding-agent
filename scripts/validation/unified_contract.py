"""Independent synthetic calculator acceptance; never writes business implementation."""
import argparse
import ast
import copy
import importlib
import io
import json
from pathlib import Path
import sys
import unittest


def preserves_tests(original, candidate):
    def same_nodes(old,new):
        for node in old:
            if isinstance(node,ast.ClassDef):
                matches=[n for n in new if isinstance(n,ast.ClassDef) and n.name==node.name]
                if len(matches)!=1:return False
                other=matches[0]
                if any(ast.dump(ast.Module(body=a,type_ignores=[]))!=ast.dump(ast.Module(body=b,type_ignores=[])) for a,b in ((node.bases,other.bases),(node.decorator_list,other.decorator_list),(node.keywords,other.keywords))):return False
                if not same_nodes(node.body,other.body):return False
            elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                matches=[n for n in new if type(n) is type(node) and n.name==node.name]
                if len(matches)!=1:return False
                other=matches[0]
                before,after=copy.deepcopy(node),copy.deepcopy(other)
                before.body=[];after.body=[]
                if ast.dump(before)!=ast.dump(after) or len(other.body)<len(node.body):return False
                # Appending assertions is legitimate; inserting return/skip or
                # changing/removing any original body statement is not.
                if any(ast.dump(a)!=ast.dump(b) for a,b in zip(node.body,other.body)):return False
            else:
                exact=[n for n in new if ast.dump(n)==ast.dump(node)]
                if not exact:return False
        return True
    return same_nodes(ast.parse(original).body,ast.parse(candidate).body)


class InputContract(unittest.TestCase):
    def test_valid_numbers(self):
        from calculator import add
        self.assertEqual(add(3,2),5)
        self.assertEqual(add(1.5,2.5),4)
        self.assertEqual(add(-2,3),1)

    def test_reject_invalid_and_nonfinite(self):
        from calculator import add
        for value in (True,False,'2',None,float('nan'),float('inf'),-float('inf')):
            for left in (True,False):
                with self.subTest(value=repr(value),left=left),self.assertRaises(ValueError):
                    add(value,1) if left else add(1,value)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--input-validation',action='store_true')
    parser.add_argument('--structure-only',action='store_true')
    args=parser.parse_args()
    original=args.original.read_text(encoding='utf-8-sig')
    candidate=(args.project/'tests/test_calc.py').read_text(encoding='utf-8-sig')
    preserved=preserves_tests(original,candidate)
    report={'original_assertions_preserved':preserved,'executed':False}
    if args.structure_only:
        print(json.dumps(report));return 0 if preserved else 1
    sys.path.insert(0,str(args.project.resolve()))
    namespace={'__name__':'frozen_original_test'}
    exec(compile(original,'frozen_original_test.py','exec'),namespace)
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(value) for value in namespace.values() if isinstance(value,type) and issubclass(value,unittest.TestCase))
    if args.input_validation:suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(InputContract))
    output=io.StringIO();result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    report.update(executed=True,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),passed=result.wasSuccessful(),summary=output.getvalue()[-2500:])
    print(json.dumps(report,ensure_ascii=False))
    return 0 if preserved and result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
