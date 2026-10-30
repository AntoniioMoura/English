from app.domain.score import builder_score, recall_score, word_accuracy


def test_word_accuracy_counts_words_already_right():
    assert word_accuracy("i have to look at my book before go out",
                         "i have to look for my book before going out") == 80  # 8 de 10 palavras


def test_case_punctuation_and_contractions_do_not_cost_points():
    assert word_accuracy("i did not play yesterday", "I didn't play yesterday.") == 100


def test_recall_score():
    assert recall_score("correct", "I was tired", None, None, "I was tired.") == 100
    assert recall_score("needs_review", "x", None, None, "y") is None
    assert recall_score(None, "x", None, None, "y") is None
    # um erro numa frase longa ainda fica abaixo de 100
    assert recall_score("incorrect", "I didn't played yesterday because I was very tired today",
                        "I didn't play yesterday because I was very tired today", None, "") == 91
    assert recall_score("incorrect", "a b c d e f g h i j k l m n o p q r s t u v w x y z",
                        "a b c d e f g h i j k l m n o p q r s t u v w x y zz", None, "") == 95
    # erro de sentido sem correção pontual: compara com a tradução válida
    assert recall_score("incorrect", "I am looking at my keys", None, "I am looking for my keys", "") == 83  # 5 de 6


def test_builder_score():
    assert builder_score("i wanted to buy a car", None, True) == 100
    assert builder_score("so i will go to wait", "so i will wait", False) == 67
