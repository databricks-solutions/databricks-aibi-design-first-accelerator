import hashlib
from pathlib import Path
import re
import unittest

class CacheGateTests(unittest.TestCase):
    def setUp(self):
        text=(Path(__file__).resolve().parents[1]/'agent_skills/v2/prompts/data_layer/validation.md').read_text()
        source=next(b for b in re.findall(r'```python\n(.*?)```',text,re.S) if 'def assess_erd_cache(' in b)
        ns={}
        exec(compile(source,'validation.md','exec'),ns)
        self.gate=ns['assess_erd_cache']
        self.digest=hashlib.sha256(b'original image').hexdigest()

    def test_mismatched_hash_is_miss_without_mutation(self):
        candidate={'_erd_image_hash':'a'*64,'tables':[{'name':'entity'}]}
        result=self.gate(candidate,self.digest)
        self.assertEqual(result['status'],'MISS')
        self.assertEqual(candidate['_erd_image_hash'],'a'*64)

    def test_missing_hash_or_invalid_document_is_miss(self):
        for candidate in (None,[],{}, {'tables':[{}]}):
            self.assertEqual(self.gate(candidate,self.digest)['status'],'MISS')

    def test_equal_hash_is_only_candidate(self):
        self.assertEqual(self.gate({'_erd_image_hash':self.digest,'tables':[{}]},self.digest)['status'],'CANDIDATE')

    def test_invalid_current_digest_is_authority_failure(self):
        with self.assertRaisesRegex(RuntimeError,'ERD_INPUT_AUTHORITY_ERROR'):
            self.gate({},'not-a-digest')

    def test_empty_inventory_is_miss(self):
        self.assertEqual(self.gate({'_erd_image_hash':self.digest,'tables':[]},self.digest)['status'],'MISS')
