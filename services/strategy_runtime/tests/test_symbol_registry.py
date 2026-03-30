# services/strategy_runtime/tests/test_symbol_registry.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from symbol_registry import SymbolRegistry

def test_register_and_lookup():
    reg = SymbolRegistry(max_symbols=10)
    idx = reg.register("NSE_EQ|INE002A01018")
    assert idx == 0
    assert reg.get_id("NSE_EQ|INE002A01018") == 0
    assert reg.get_key(0) == "NSE_EQ|INE002A01018"

def test_same_key_returns_same_id():
    reg = SymbolRegistry(max_symbols=10)
    a = reg.register("NSE_EQ|INE002A01018")
    b = reg.register("NSE_EQ|INE002A01018")
    assert a == b

def test_unknown_key_returns_none():
    reg = SymbolRegistry(max_symbols=10)
    assert reg.get_id("NSE_EQ|UNKNOWN") is None

def test_capacity_limit():
    reg = SymbolRegistry(max_symbols=2)
    reg.register("NSE_EQ|AAA")
    reg.register("NSE_EQ|BBB")
    result = reg.register("NSE_EQ|CCC")
    assert result is None  # Registry full
