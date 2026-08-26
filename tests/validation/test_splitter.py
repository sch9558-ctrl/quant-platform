from quant.validation import splitter


def test_walk_forward_folds_are_contiguous_and_non_overlapping():
    cfg = {"in_sample_years": 4, "validation_years": 1, "out_of_sample_years": 1, "step_years": 1}
    folds = splitter.generate_walk_forward_folds("2000-01-01", "2010-12-31", cfg)
    assert len(folds) >= 3
    for f in folds:
        assert f.is_start < f.is_end < f.val_start <= f.val_end < f.oos_start <= f.oos_end
    # step of 1 year -> consecutive folds' IS windows start 1 year apart
    for a, b in zip(folds, folds[1:]):
        assert (b.is_start - a.is_start).days in range(360, 372)


def test_fixed_split_covers_full_range():
    fold = splitter.fixed_split("2020-01-01", "2020-12-31",
                                 {"in_sample_pct": 0.6, "validation_pct": 0.2, "out_of_sample_pct": 0.2})
    assert fold.is_start.strftime("%Y-%m-%d") == "2020-01-01"
    assert fold.oos_end.strftime("%Y-%m-%d") == "2020-12-31"
    assert fold.is_end < fold.val_start
    assert fold.val_end < fold.oos_start


def test_get_folds_uses_walk_forward_when_enough_history():
    folds = splitter.get_folds("2010-01-01", "2023-12-31")
    assert len(folds) > 1


def test_get_folds_falls_back_to_fixed_split_for_short_history():
    folds = splitter.get_folds("2022-01-01", "2023-06-01")
    assert len(folds) == 1
    assert folds[0].is_start.strftime("%Y-%m-%d") == "2022-01-01"
