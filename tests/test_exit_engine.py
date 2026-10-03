from quant.trading.exit_engine import ExitEngine

def test_chandelier_stop_never_moves_down():
    e=ExitEngine()
    a=e.update(120,4,115,100,5,previous_trailing_stop=108)
    b=e.update(118,5,114,100,6,previous_trailing_stop=a.trailing_stop)
    assert b.trailing_stop>=a.trailing_stop

def test_time_stop_and_take_profit():
    e=ExitEngine()
    assert e.update(103,1,101,100,15).signal=="TIME_EXPIRED_EXIT"
    assert e.update(120,4,109,100,8).signal=="TAKE_PROFIT"
