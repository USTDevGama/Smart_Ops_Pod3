from app.scoring.validity import ClientMessage, question_validity

REFERENCE = "Warehouse picking dashboard with a fixed price and a go-live date."


def _msg(number, text, level):
    return ClientMessage(number=number, text=text, level=level)


def test_a_normal_chat_is_all_valid():
    messages = [
        _msg(1, "When is the dashboard go-live date?", 1),
        _msg(2, "What does the fixed price cover exactly?", 2),
        _msg(3, "Who pays when the picking dashboard slips?", 2),
    ]

    assert question_validity(messages, 4, REFERENCE) == {1: True, 2: True, 3: True}


def test_a_level_jump_of_more_than_one_step_is_invalid():
    messages = [
        _msg(1, "When is the dashboard go-live date?", 1),
        _msg(2, "What does the fixed price cover exactly?", 3),
    ]

    assert question_validity(messages, 4, REFERENCE) == {1: True, 2: False}


def test_a_missing_or_out_of_ladder_level_is_invalid():
    messages = [
        _msg(1, "When is the dashboard go-live date?", None),
        _msg(2, "What does the fixed price cover exactly?", 5),
    ]

    assert question_validity(messages, 4, REFERENCE) == {1: False, 2: False}


def test_a_repeated_question_is_invalid():
    messages = [
        _msg(1, "When is the dashboard go-live date?", 1),
        _msg(2, "When is the dashboard go-live date?", 1),
    ]

    assert question_validity(messages, 4, REFERENCE) == {1: True, 2: False}


def test_a_message_unrelated_to_the_documents_is_invalid():
    messages = [_msg(1, "Tell me about your favourite holiday destinations", 1)]

    assert question_validity(messages, 4, REFERENCE) == {1: False}


def test_with_no_reference_text_the_overlap_rule_is_skipped():
    messages = [_msg(1, "Tell me about your favourite holiday destinations", 1)]

    assert question_validity(messages, 4, "") == {1: True}


def test_an_empty_message_is_invalid():
    assert question_validity([_msg(1, "   ", 1)], 4, "") == {1: False}
