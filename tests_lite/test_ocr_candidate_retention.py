from lite_app.ocr.base import OCRToken
from lite_app.ocr.paddleocr_v6 import PaddleOCRv6Provider


def _token(score: float) -> OCRToken:
    return OCRToken(
        id=f"t-{score}",
        text="材料",
        confidence=score,
        polygon=[[0, 0], [1, 0], [1, 1], [0, 1]],
        bbox=[0, 0, 1, 1],
        center_x=0.5,
        center_y=0.5,
    )


def test_low_confidence_tokens_are_retained_as_candidates_only() -> None:
    provider = PaddleOCRv6Provider(
        retention_score=0.25,
        acceptance_score=0.45,
    )

    retained = provider.retain_tokens(
        [_token(0.20), _token(0.31), _token(0.82)]
    )

    assert [token.confidence for token in retained] == [0.31, 0.82]
    assert retained[0].candidate_only is True
    assert retained[1].candidate_only is False
