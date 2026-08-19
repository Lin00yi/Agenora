from src.retrieval.assess import admit_hits, merge_assessments


def test_admit_hits_miss_vs_hit() -> None:
    low = [{"id": "a", "score": 0.39, "payload": {}}]
    admitted, assessment = admit_hits(low, min_dense_score=0.4, final_limit=3)
    assert admitted == []
    assert assessment.status == "miss"
    assert assessment.candidate_count == 1
    assert assessment.max_score == 0.39

    high = [{"id": "b", "score": 0.81, "payload": {}}]
    admitted, assessment = admit_hits(high, min_dense_score=0.4, final_limit=3)
    assert len(admitted) == 1
    assert assessment.status == "hit"


def test_merge_assessments_prefers_hit() -> None:
    _, miss = admit_hits([{"score": 0.1}], min_dense_score=0.4, final_limit=3)
    _, hit = admit_hits([{"score": 0.9}], min_dense_score=0.4, final_limit=3)
    merged = merge_assessments([miss, hit])
    assert merged.status == "hit"
    assert merged.candidate_count == 2
    assert merged.admitted_count == 1
