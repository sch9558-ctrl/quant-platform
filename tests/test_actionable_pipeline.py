from quant.pipeline.daily_pipeline import build_actionable_signals


def _dashboard(approved, cleared, complete=True):
    return {
        "markets":{
            "korea":{
                "blocked":False,
                "as_of":"2026-10-02",
                "candidates":[{
                    "symbol":"005930",
                    "company":"삼성전자",
                    "market":"korea",
                    "price":70000,
                    "trade_plan":{
                        "entry_low":69000,
                        "entry_high":70000,
                        "target_1":80000,
                        "target_2":85000,
                        "stop_loss":66000,
                        "risk_reward_1":2.5,
                    },
                    "institutional_overlay":{
                        "approved":approved,
                        "risk_cleared":cleared,
                        "external_checks_complete":complete,
                        "net_alpha_pct":5.0,
                        "position_weight":0.08,
                        "reasons":[],
                    },
                }],
            },
            "us":{"blocked":True,"candidates":[]},
        }
    }


def test_actionable_buy_requires_backend_risk_clearance():
    blocked=build_actionable_signals(_dashboard(False,False,False),{})
    assert blocked["signals"][0]["action"]=="REVIEW"
    assert blocked["signals"][0]["recommended_quantity"]>0

    approved=build_actionable_signals(_dashboard(True,True,True),{})
    sig=approved["signals"][0]
    assert sig["action"]=="BUY"
    assert sig["risk_cleared"] is True
    assert sig["recommended_weight"]<=0.10
    assert sum(x["quantity"] for x in sig["execution_schedule"])==sig["recommended_quantity"]
