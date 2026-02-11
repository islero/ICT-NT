# Contributing to ICT Trading Strategy Framework

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a new branch for your feature or bugfix
4. Make your changes
5. Test your changes thoroughly
6. Submit a pull request

## Development Setup

### Prerequisites

- Python 3.11+
- pip or uv package manager
- Git

### Installation

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/ICT-NT.git
cd "ICT NT"

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest
```

## Code Style

- Follow PEP 8 style guidelines
- Use type hints where possible
- Write docstrings for all public methods and classes
- Keep functions focused and modular
- Use meaningful variable and function names

### Example

```python
from typing import Optional
from core.enums.rule_signal import RuleSignal

class MyRule(RuleBase):
    """
    Brief description of what this rule does.

    Attributes:
        param1: Description of param1
        param2: Description of param2
    """

    def __init__(self, param1: int, param2: str) -> None:
        """Initialize the rule with given parameters."""
        self.param1 = param1
        self.param2 = param2

    def check(self) -> RuleSignal:
        """
        Check if the rule conditions are met.

        Returns:
            RuleSignal indicating LONG, SHORT, or NO_SIGNAL
        """
        # Implementation
        pass
```

## Testing

All new features and bug fixes should include tests.

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_my_feature.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=.
```

### Continuous Integration

This project uses GitHub Actions for automated testing and code quality checks. Every push and pull request triggers:

1. **Test Workflow** (`.github/workflows/test.yml`):
   - Runs tests on Ubuntu, macOS, and Windows
   - Tests against Python 3.11 and 3.12
   - Validates module imports
   - Generates coverage reports

2. **Code Quality Workflow** (`.github/workflows/code-quality.yml`):
   - Code formatting checks (Black, isort)
   - Linting (flake8, pylint)
   - Type checking (mypy)
   - Security scanning (Bandit, Safety)

All checks must pass before a pull request can be merged. You can run these checks locally before pushing:

```bash
# Code formatting
black .
isort .

# Linting
flake8 .

# Type checking
mypy .

# Security check
bandit -r .
```

### Writing Tests

```python
import pytest
from my_module import MyClass

def test_my_feature():
    """Test description."""
    # Arrange
    obj = MyClass(param=value)

    # Act
    result = obj.method()

    # Assert
    assert result == expected_value

def test_edge_case():
    """Test edge case description."""
    with pytest.raises(ValueError):
        MyClass(param=invalid_value)
```

## Commit Messages

Write clear, descriptive commit messages:

```
Add feature: Brief description of feature

- Detailed point 1
- Detailed point 2
- Fixes #issue_number
```

Types of commits:
- `Add feature:` New functionality
- `Fix:` Bug fixes
- `Refactor:` Code restructuring
- `Docs:` Documentation changes
- `Test:` Test additions or modifications
- `Chore:` Maintenance tasks

## Pull Request Process

1. **Update Documentation**: Ensure README.md and docstrings are updated
2. **Add Tests**: Include tests for new features
3. **Run Tests**: Ensure all tests pass
4. **Update CHANGELOG**: Add entry describing your changes
5. **Create PR**: Write a clear description of your changes

### PR Description Template

```markdown
## Description
Brief description of the changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
Describe the tests you ran and their results

## Checklist
- [ ] Code follows project style guidelines
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] All tests pass
- [ ] No new warnings
```

## Adding New Features

### New Trading Rules

1. Create file in `rules/` directory
2. Inherit from appropriate base class (`RuleBase` or `QuoteTickRuleBase`)
3. Implement required methods
4. Add comprehensive tests
5. Document usage examples

### New Indicators

1. Create file in `indicators/` directory
2. Use vectorized operations (NumPy/Pandas)
3. Handle edge cases (NaN, insufficient data)
4. Add unit tests with various data scenarios
5. Document parameters and return values

### New Strategies

1. Create directory in `strategies/`
2. Inherit from `RuleBasedStrategy`
3. Define entry, exit, and position management rules
4. Add configuration class
5. Include backtest example
6. Document strategy logic and parameters

## Code Review

All submissions require review before merging. Reviewers will check:

- Code quality and style
- Test coverage
- Documentation completeness
- Performance implications
- Backward compatibility

## Bug Reports

When reporting bugs, include:

1. **Description**: Clear description of the issue
2. **Steps to Reproduce**: Minimal code example
3. **Expected Behavior**: What should happen
4. **Actual Behavior**: What actually happens
5. **Environment**: Python version, OS, dependencies
6. **Error Messages**: Full error traceback

## Feature Requests

When requesting features, include:

1. **Use Case**: Why is this feature needed?
2. **Proposed Solution**: How should it work?
3. **Alternatives**: Other solutions you've considered
4. **Examples**: Code examples if applicable

## Questions and Support

- **Documentation**: Check README.md first
- **Issues**: Search existing issues before creating new ones
- **Discussions**: Use GitHub Discussions for questions

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

## Thank You!

Your contributions help make this project better for everyone. We appreciate your time and effort!
