import unittest

from services import memory
from services.memory import MemoryItem


def _items(*texts):
    return [MemoryItem(str(index), text) for index, text in enumerate(texts, 1)]


class LoadTests(unittest.TestCase):
    def test_reads_stored_entries_with_their_ids(self):
        raw = [{"id": "4", "text": "  likes   hiking "}, {"id": "9", "text": "avoids conflict"}]
        self.assertEqual(
            memory.load(raw),
            [MemoryItem("4", "likes hiking"), MemoryItem("9", "avoids conflict")],
        )

    def test_upgrades_a_legacy_plain_string_list(self):
        # An old state file has no ids; they are minted on first read so nothing
        # has to be migrated by hand.
        self.assertEqual(memory.load(["first", "second"]), _items("first", "second"))

    def test_mints_ids_for_missing_and_colliding_ones(self):
        raw = [{"text": "no id"}, {"id": "7", "text": "has id"}, {"id": "7", "text": "same id"}]
        self.assertEqual(
            memory.load(raw),
            [MemoryItem("1", "no id"), MemoryItem("7", "has id"), MemoryItem("8", "same id")],
        )

    def test_drops_junk_entries(self):
        raw = ["keep", "", "   ", 42, None, {"text": ""}, {"id": "2"}, "keep"]
        self.assertEqual(memory.load(raw), [MemoryItem("1", "keep")])

    def test_non_list_state_reads_as_empty(self):
        for raw in (None, "facts", {"text": "fact"}, 7):
            with self.subTest(raw=raw):
                self.assertEqual(memory.load(raw), [])

    def test_dump_round_trips(self):
        items = _items("first", "second")
        self.assertEqual(memory.load(memory.dump(items)), items)


class RenderTests(unittest.TestCase):
    def test_texts_drops_the_ids(self):
        self.assertEqual(memory.texts(_items("first", "second")), ["first", "second"])

    def test_render_shows_the_id_the_model_must_quote(self):
        self.assertEqual(memory.render(_items("first", "second")), "[1] first\n[2] second")


class AdoptTests(unittest.TestCase):
    """Taking over a list edited outside the bot — a hand-edited Notion page."""

    def test_surviving_text_keeps_its_id(self):
        items = _items("first", "second")
        # Reordered and one line dropped, but both texts are untouched.
        self.assertEqual(
            memory.adopt(items, ["second", "first"]),
            [MemoryItem("2", "second"), MemoryItem("1", "first")],
        )

    def test_a_reworded_line_becomes_a_new_entry(self):
        result = memory.adopt(_items("keep", "old wording"), ["keep", "new wording"])
        self.assertEqual(result, [MemoryItem("1", "keep"), MemoryItem("3", "new wording")])

    def test_added_lines_get_fresh_ids_and_junk_is_dropped(self):
        result = memory.adopt(_items("keep"), ["keep", "  added  ", "", "   ", "keep"])
        self.assertEqual(result, [MemoryItem("1", "keep"), MemoryItem("2", "added")])

    def test_an_emptied_page_clears_the_list(self):
        self.assertEqual(memory.adopt(_items("keep"), []), [])


class ApplyOpsTests(unittest.TestCase):
    def test_create_appends_with_a_fresh_id(self):
        items = _items("known")
        result = memory.apply_ops(items, [{"action": "create", "text": "  fresh  fact "}])
        self.assertEqual(result, [MemoryItem("1", "known"), MemoryItem("2", "fresh fact")])

    def test_modify_rewrites_in_place_and_keeps_the_id(self):
        result = memory.apply_ops(
            _items("keep", "vague fact"),
            [{"action": "modify", "id": "2", "text": "sharp fact"}],
        )
        self.assertEqual(result, [MemoryItem("1", "keep"), MemoryItem("2", "sharp fact")])

    def test_delete_drops_only_its_target(self):
        result = memory.apply_ops(_items("keep", "gone"), [{"action": "delete", "id": "2"}])
        self.assertEqual(result, [MemoryItem("1", "keep")])

    def test_delete_wins_over_a_modify_of_the_same_entry(self):
        ops = [{"action": "modify", "id": "2", "text": "revived"}, {"action": "delete", "id": "2"}]
        self.assertEqual(memory.apply_ops(_items("keep", "gone"), ops), [MemoryItem("1", "keep")])

    def test_an_unknown_id_is_a_no_op_never_a_loss(self):
        # The whole point of addressing by id: a reference the model gets wrong
        # cannot delete the wrong entry or duplicate the one it meant to edit.
        items = _items("keep")
        for op in ({"action": "delete", "id": "99"},
                   {"action": "modify", "id": "99", "text": "orphan"},
                   {"action": "delete", "id": ""},
                   {"action": "modify", "text": "no id at all"}):
            with self.subTest(op=op):
                self.assertEqual(memory.apply_ops(items, [op]), items)

    def test_an_id_freed_in_this_pass_is_not_handed_to_a_new_entry(self):
        ops = [{"action": "delete", "id": "2"}, {"action": "create", "text": "fresh"}]
        result = memory.apply_ops(_items("keep", "gone"), ops)
        self.assertEqual(result, [MemoryItem("1", "keep"), MemoryItem("3", "fresh")])

    def test_a_created_duplicate_of_a_known_fact_is_dropped(self):
        items = _items("keep")
        self.assertEqual(memory.apply_ops(items, [{"action": "create", "text": "KEEP"}]), items)

    def test_malformed_ops_leave_the_list_intact(self):
        items = _items("keep")
        for ops in ([], [{}], ["not an object"], [{"action": "rewrite", "id": "1"}],
                    [{"action": "create"}], [{"action": "create", "text": "   "}],
                    [{"action": "modify", "id": "1"}], "not a list", None, {"action": "create"}):
            with self.subTest(ops=ops):
                self.assertEqual(memory.apply_ops(items, ops), items)

    def test_a_batch_applies_in_one_pass(self):
        ops = [
            {"action": "create", "text": "new trait"},
            {"action": "delete", "id": "3"},
            {"action": "modify", "id": "2", "text": "sharpened"},
        ]
        result = memory.apply_ops(_items("keep", "vague", "stale"), ops)
        self.assertEqual(
            result,
            [MemoryItem("1", "keep"), MemoryItem("2", "sharpened"), MemoryItem("4", "new trait")],
        )

    def test_growth_is_never_capped_mechanically(self):
        # List size is guided at the prompt level only: the store must accumulate.
        ops = [{"action": "create", "text": f"fact {i}"} for i in range(500)]
        self.assertEqual(len(memory.apply_ops([], ops)), 500)


if __name__ == "__main__":
    unittest.main()
