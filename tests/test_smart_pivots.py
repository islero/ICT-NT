
import sys
import os
from unittest.mock import MagicMock

# --- MOCKING NAUTILUS TRADER ---
# We mock the dependencies so we can test the logic purely
sys.modules["nautilus_trader"] = MagicMock()
sys.modules["nautilus_trader.indicators"] = MagicMock()
sys.modules["nautilus_trader.indicators.base"] = MagicMock()
sys.modules["nautilus_trader.model"] = MagicMock()
sys.modules["nautilus_trader.model.data"] = MagicMock()

# Define the base class for Indicator so the import works and subclassing works
class MockIndicator:
    def __init__(self, inputs=None):
        pass
    def reset(self):
        pass

sys.modules["nautilus_trader.indicators.base"].Indicator = MockIndicator
sys.modules["nautilus_trader.model.data"].Bar = MagicMock()

# Ensure we can import from the project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now we can import the indicator under test
from indicators.smart_pivot_points import SmartPivotPoints

# Mock Bar object for our use
class MockBar:
    def __init__(self, o, h, l, c, t=0):
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.ts_event = t

def run_test():
    print("--- Stark Pivot Points Test (Mocked Environment) ---")
    indicator = SmartPivotPoints()
    
    # Sequence of OHLC
    # 1. Start High
    # 2. Establish Down Trend
    # 3. Deep Pullback
    # 4. Break Down
    
    prices = [
        # Initialization
        (100, 105, 95, 100),   # 0. Initial Range
        (100, 102, 90, 92),    # 1. Drop, creates Low 90
        (92, 95, 91, 93),      # 2. Inside
        (93, 93, 80, 80),      # 3. BREAK DOWN (Close 80 < 90). Trend -> DOWN (-1).
        
        # Deep Pullback Phase
        (80, 85, 80, 85),      # 4. Pullback start
        (85, 95, 85, 95),      # 5. Deep Pullback to 95. Candidate LH = 95.
        (95, 96, 94, 94),      # 6. Higher internal high (96). Candidate LH = 96.
        (94, 94, 88, 88),      # 7. Internal low
        (88, 92, 88, 90),      # 8. Another lower high (92) internally. 
        
        # Continuation / BOS
        (90, 90, 75, 75),      # 9. CRASH to 75. Breaks Major Low (80).
                               #    EXPECTATION: Confirm 96 as New Major High.
                               #    New Major Low = 75.
    ]
    
    print(f"{'Bar':<5} | {'Close':<7} | {'High':<7} | {'Low':<7} | {'Trend':<5} | {'MajorHigh':<10} | {'MajorLow':<10} | {'Events'}")
    print("-" * 80)
    
    for i, p in enumerate(prices):
        bar = MockBar(p[0], p[1], p[2], p[3], t=i*1000)
        indicator.handle_bar(bar)
        
        trend_str = "DOWN" if indicator.trend == -1 else "UP" if indicator.trend == 1 else "NONE"
        mh = str(indicator.major_high) if indicator.major_high else "-"
        ml = str(indicator.major_low) if indicator.major_low else "-"
        
        event = ""
        if indicator.is_new_major_high: event += "[NEW MAJOR HIGH] "
        if indicator.is_new_major_low: event += "[NEW MAJOR LOW] "
        
        print(f"{i:<5} | {bar.close:<7} | {bar.high:<7} | {bar.low:<7} | {trend_str:<5} | {mh:<10} | {ml:<10} | {event}")

if __name__ == "__main__":
    run_test()
