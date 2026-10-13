import pytest

from shortener.codegen import ALPHABET, generate_code, validate_alias
from shortener.errors import InvalidAlias


def test_generate_code_length_and_alphabet():
    code = generate_code(9)
    assert len(code) == 9 and set(code) <= set(ALPHABET)


def test_generate_code_is_not_constant():
    assert len({generate_code() for _ in range(50)}) == 50


@pytest.mark.parametrize("alias", ["abc", "my-link_1", "A" * 32])
def test_valid_aliases(alias):
    assert validate_alias(alias) == alias


@pytest.mark.parametrize("alias", ["ab", "A" * 33, "has space", "semi;colon", "api", "HEALTHZ", ""])
def test_invalid_aliases(alias):
    with pytest.raises(InvalidAlias):
        validate_alias(alias)
