import tempfile
import unittest
from pathlib import Path

from prepare_review import FIELDS, apply_set, build_html, load_rows, save_edits, save_rows


class ReviewSavingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = []
        for filename, species, count in [('cat/cat_001.jpg', 'cat', '1'), ('neg_hare/neg_hare_001.jpg', 'none', '0')]:
            row = dict.fromkeys(FIELDS, '')
            row.update(filename=filename, species=species, true_count=count,
                       condition='clear', role='pet/pest', attribution='Wü, "photographer"\nCC BY',
                       custom_metadata='preserve this extra column')
            self.rows.append(row)
        save_rows(self.root / 'ground_truth.csv', self.rows)
        self.before = (self.root / 'ground_truth.csv').read_bytes()

    def edit(self, index=0, **changes):
        row = self.rows[index]
        return dict(filename=row['filename'], before={k: row[k] for k in ['true_count', 'condition', 'verified']}, changes=changes)

    def test_round_trip_preserves_metadata_and_exact_backup(self):
        result = save_edits(self.root, [self.edit(true_count='2', condition='other', verified='ok')])
        self.assertEqual(result[0]['true_count'], '2')
        self.assertEqual(result[0]['verified'], 'ok')
        self.assertEqual(result[1], self.rows[1])
        for field in self.rows[0]:
            if field not in {'true_count', 'condition', 'verified'}:
                self.assertEqual(result[0][field], self.rows[0][field])
        self.assertEqual(list(result[0]), list(self.rows[0]))
        self.assertEqual((self.root / 'ground_truth.backup.csv').read_bytes(), self.before)
        self.assertEqual(load_rows(self.root / 'ground_truth.csv'), result)

    def test_failed_batch_leaves_entire_csv_unchanged(self):
        stale = self.edit(1, verified='ok')
        stale['before']['true_count'] = '9'
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            save_edits(self.root, [self.edit(true_count='2'), stale])
        self.assertEqual((self.root / 'ground_truth.csv').read_bytes(), self.before)

    def test_rejects_protected_fields_and_invalid_labels(self):
        for changes in [dict(species='dog'),dict(role='pest'),dict(true_count='-1'),dict(true_count='1.5'),
                        dict(condition='dead'),dict(condition='clear;night'),dict(condition='night;night'),dict(verified='yes'),
                        dict(condition='multiple'),dict(condition='small'),dict(condition='night;other'),dict(condition='')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                save_edits(self.root, [self.edit(**changes)])
        with self.assertRaises(ValueError):
            save_edits(self.root, [self.edit(1, true_count='1')])
        self.assertEqual((self.root / 'ground_truth.csv').read_bytes(), self.before)

    def test_preserves_unedited_legacy_labels(self):
        self.rows[0]['condition'] = 'dead'
        save_rows(self.root / 'ground_truth.csv', self.rows)
        result = save_edits(self.root, [self.edit(verified='review')])
        self.assertEqual(result[0]['condition'], 'dead')
        corrected = dict(filename=result[0]['filename'], before={k: result[0][k] for k in ['true_count','condition','verified']}, changes={'condition':'other'})
        self.assertEqual(save_edits(self.root,[corrected])[0]['condition'],'other')

    def test_accepts_each_condition_and_blank_only_when_rejected(self):
        for value in ['clear', 'night', 'other']:
            row = save_edits(self.root, [self.edit(condition=value)])[0]
            self.assertEqual(row['condition'], value)
            self.rows[0] = row
        row = save_edits(self.root, [self.edit(condition='', verified='reject')])[0]
        self.assertEqual((row['condition'], row['verified']), ('', 'reject'))

    def test_set_command_uses_same_validation(self):
        rows = [dict(r) for r in self.rows]
        apply_set(rows, 'cat_001:condition=night')
        apply_set(rows, 'cat_001:role=pet')
        self.assertEqual((rows[0]['condition'], rows[0]['role']), ('night', 'pet'))
        for spec in ['cat_001:condition=night;small', 'cat_001:condition=multiple', 'cat_001:verified=yes',
                     'cat_001:role=feral', 'neg_hare_001:true_count=2']:
            with self.subTest(spec=spec), self.assertRaises(SystemExit):
                apply_set(rows, spec)

    def test_never_overwrites_existing_backup(self):
        (self.root / 'ground_truth.backup.csv').write_bytes(b'previous backup')
        save_edits(self.root,[self.edit(verified='ok')])
        self.assertEqual((self.root / 'ground_truth.backup.csv').read_bytes(),b'previous backup')

    def test_embedded_data_cannot_close_script(self):
        self.rows[0]['attribution'] = '</script><script>alert("unexpected")</script>'
        page = build_html(self.rows,self.root).read_text(encoding='utf-8')
        self.assertNotIn(self.rows[0]['attribution'],page)
        self.assertIn('\\u003c/script\\u003e',page)


if __name__ == '__main__':
    unittest.main()
