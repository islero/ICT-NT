# ICT Trading Strategy Framework

A sophisticated algorithmic trading framework built on [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) that implements Inner Circle Trader (ICT) concepts and Turtle Soup strategies for systematic trading.

## Features

- **Rule-Based Trading System**: Flexible, modular rule engine for building complex trading strategies
- **ICT Concepts Implementation**:
  - Fair Value Gaps (FVG)
  - Smart Pivot Points
  - Liquidity Pools
  - Market Structure Analysis
  - Daily/Weekly Context Rules
- **Turtle Soup Strategy**: Multi-timeframe implementation with position management
- **Advanced Position Management**:
  - Trailing stop loss
  - Partial close rules
  - Move to breakeven
  - SMA-based exit signals
- **Risk Management**: Fixed risk sizing and reward-risk ratio validation
- **Backtesting**: High-performance backtesting engine with detailed analytics

## Performance

Latest backtest results on E-mini S&P 500 Futures (ESZ5):

```
============================================================
BACKTEST RESULTS
============================================================
Trader ID:        BACKTESTER-001
Run ID:           f48cfad3-2e2c-4c67-bd15-503910f1c56f
Backtest Period:  2025-01-01 23:01:00 → 2025-10-20 00:00:00
Elapsed Time:     0.03 seconds
Iterations:       282,241
Total Orders:     246
Total Positions:  79

============================================================
PNL STATISTICS (USD)
============================================================
PnL (total):      $4,055.50
PnL% (total):     13.52%
Expectancy:       $51.34
Win Rate:         35.44%
Max Winner:       $1,320.00
Avg Winner:       $713.21
Min Winner:       $588.00
Max Loser:        $-389.25
Avg Loser:        $-312.04
Min Loser:        $-199.50

============================================================
RETURN STATISTICS
============================================================
Sharpe Ratio (252d):   1.8668
Sortino Ratio (252d):  3.5886
Profit Factor:         1.3416
Returns Volatility:    0.1345
Risk Return Ratio:     0.1176
Avg Return:            0.0731%
Avg Win Return:        0.8105%
Avg Loss Return:       -0.3317%
```

## Installation

### Prerequisites

- Python 3.11 or higher
- pip or uv package manager

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd "ICT NT"
```

2. Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Project Structure

```
.
├── core/                    # Core framework components
│   ├── rules/              # Base rule classes
│   ├── strategies/         # Base strategy classes
│   └── enums/              # Enums and constants
├── rules/                   # Trading rule implementations
│   ├── entry_turtle_soup_rule.py
│   ├── search_liquidity_pools_rule.py
│   ├── market_structure_rule.py
│   ├── weekly_context_rule.py
│   ├── daily_bias_rule.py
│   └── sma_exit_rule.py
├── strategies/              # Strategy implementations
│   ├── turtle_soup/        # Turtle Soup strategy
│   └── ict/                # ICT-based strategies
├── indicators/              # Custom indicators
│   ├── pivot_points_high_low.py
│   ├── smart_pivot_points.py
│   ├── fair_value_gap.py
│   └── fibonacci_levels.py
├── risk/                    # Risk management modules
├── tests/                   # Unit tests
├── notebooks/              # Jupyter notebooks for analysis
└── data/                   # Historical data storage
```

## Usage

### Running a Backtest

```python
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.backtest.config import BacktestRunConfig

# Configure and run backtest
config = BacktestRunConfig(...)
node = BacktestNode(configs=[config])
results = node.run()
```

See `backtest_benchmark.py` for a complete example.

### Creating Custom Rules

```python
from core.rules.rule_base import RuleBase
from core.enums.rule_signal import RuleSignal

class MyCustomRule(RuleBase):
    def check(self) -> RuleSignal:
        # Implement your trading logic
        return RuleSignal.LONG if condition else RuleSignal.NO_SIGNAL
```

### Building a Strategy

```python
from core.strategies.rule_based_strategy import RuleBasedStrategy

strategy = RuleBasedStrategy(
    entry_rules=[entry_rule1, entry_rule2],
    exit_rules=[exit_rule],
    position_management_rules=[trailing_stop, partial_close]
)
```

## Configuration

Create a `.env` file in the project root for environment-specific settings:

```env
# Add your configuration here
```

## Testing

Run the test suite:

```bash
pytest
```

Run specific tests:

```bash
pytest tests/test_smart_pivot_points.py -v
```

## Key Concepts

### ICT Methodology
- **Fair Value Gaps**: Price imbalances that act as magnets
- **Liquidity Pools**: Areas of accumulated stop losses
- **Market Structure**: Higher highs, higher lows analysis
- **Order Blocks**: Key institutional price levels

### Turtle Soup
A counter-trend strategy that fades false breakouts from consolidation ranges, originally designed to exploit failures of the Turtle Trading System breakout signals.

## Development

### Adding New Rules

1. Create a new file in `rules/` directory
2. Inherit from `RuleBase` or `QuoteTickRuleBase`
3. Implement the `check()` method
4. Add tests in `tests/` directory

### Adding New Indicators

1. Create indicator in `indicators/` directory
2. Follow NumPy/Pandas vectorized operations for performance
3. Add unit tests with edge cases

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

See [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built on [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) - High-performance algorithmic trading platform
- ICT concepts by Michael J. Huddleston
- Turtle Soup strategy by Linda Raschke

## Disclaimer

This software is for educational and research purposes only. Trading financial instruments carries risk. Past performance does not guarantee future results. Use at your own risk.

## Support

For questions, issues, or feature requests, please open an issue on GitHub.
