"""Public README invariants; documentation checks never certify assay admission."""
import csv
import importlib.util
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('readme_public_scan', ROOT / 'tools/prepare_public.py')
public = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(public)


class ReadmeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / 'README.md').read_text(encoding='utf-8')

    def test_bilingual_sections_and_navigation(self):
        for marker in ['<a id="中文"></a>', '<a id="english"></a>',
                       '## 中文', '## English', '## Quick start · 快速开始']:
            self.assertIn(marker, self.text)
        self.assertIn('我们的 idea 与愿景', self.text)
        self.assertIn('Our idea and vision', self.text)
        self.assertIn('Scientific questions', self.text)

    def test_registry_counts_have_explicit_units(self):
        census = json.loads((ROOT / 'data/audit/census_summary.json').read_text())
        self.assertIn(str(census['registered_tasks']) + ' task rows', self.text)
        self.assertIn(str(census['source_families']) + ' source families', self.text)
        self.assertIn(str(census['package_groups']) + ' acquisition', self.text)
        self.assertIn('0 admitted tasks', self.text)
        self.assertIn('not counts of independently verified assays', self.text)

    def test_complete_package_index_matches_frozen_registry(self):
        with (ROOT / 'data/registries/download_packages_47.csv').open(encoding='utf-8-sig') as handle:
            rows = list(csv.DictReader(handle))
        expected = {r['package_group_id']: (r['canonical_source'], r['referenced_task_rows']) for r in rows}
        actual = {key: (source.strip(), count) for key, source, count in re.findall(
            r'^\| `([^`]+)` \| (.+?) \| (\d+) \|$', self.text, re.M)}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 47)

    def test_reference_links_resolve_to_public_files_or_https(self):
        refs = dict(re.findall(r'^\[([^]]+)\]: (\S+)\s*$', self.text, re.M))
        used = set(re.findall(r'(?<!!)\[[^]\n]+\]\[([^]\n]+)\]', self.text))
        self.assertEqual(used, set(refs))
        inline = re.findall(r'(?<!!)\[[^]\n]+\]\(([^)]+)\)', self.text)
        images = re.findall(r'<img[^>]+src="([^"]+)"', self.text)
        links = re.findall(r'<a[^>]+href="([^"]+)"', self.text)
        for target in list(refs.values()) + inline + images + links:
            parsed = urlsplit(target)
            with self.subTest(target=target):
                if parsed.scheme:
                    self.assertEqual(parsed.scheme, 'https')
                    self.assertTrue(parsed.netloc)
                elif parsed.path:
                    self.assertTrue((ROOT / unquote(parsed.path)).exists())

    def test_header_vector_is_accessible_and_self_contained(self):
        svg = ET.parse(ROOT / 'site/assets/rna-gym-overview.svg').getroot()
        ns = '{http://www.w3.org/2000/svg}'
        self.assertIsNotNone(svg.find(ns + 'title'))
        self.assertIsNotNone(svg.find(ns + 'desc'))
        self.assertEqual(svg.attrib['role'], 'img')
        for node in svg.iter():
            self.assertNotIn(node.tag.split('}')[-1], ['script', 'foreignObject', 'image'])
            self.assertFalse(any(key.lower().startswith('on') for key in node.attrib))
            self.assertFalse(any('href' in key for key in node.attrib))
        self.assertIn('alt="RNA-Gym:', self.text)

    def test_readme_and_header_pass_public_safety_scan(self):
        for name in ['README.md', 'site/assets/rna-gym-overview.svg']:
            with self.subTest(name=name):
                self.assertEqual(public.scan_file(ROOT / name), [])

    def test_tracks_and_scientific_limitations_remain_explicit(self):
        for track in ['Zero-shot likelihood', 'Frozen + Ridge', 'Frozen + MLP',
                      'LoRA', 'Full fine-tuning', 'Random initialization']:
            self.assertIn(track, self.text)
        for caveat in ['not an official', 'full RNA homology clearance',
                       'original-assay/condition HOLD', 'synthetic',
                       'rights review', 'human admission approval']:
            self.assertIn(caveat, self.text)

    def test_readme_only_updates_trigger_ci(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        self.assertEqual(workflow.count("      - 'README.md'"), 2)

    def test_markdown_hygiene(self):
        prose = re.sub(r'```[^\n]*\n.*?```', '', self.text, flags=re.S)
        self.assertEqual(len(re.findall(r'^# ', prose, re.M)), 1)
        self.assertEqual(self.text.count('```') % 2, 0)
        self.assertFalse(any(line.rstrip() != line for line in self.text.splitlines()))
        self.assertNotIn('__PACKAGE_ROWS__', self.text)


if __name__ == '__main__':
    unittest.main()
