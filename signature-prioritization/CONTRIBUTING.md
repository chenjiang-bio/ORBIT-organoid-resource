# Contributing to orbit-ocsp

Thank you for your interest in contributing to orbit-ocsp! This document provides guidelines for contributing to the project.

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd orbit-ocsp
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install development dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Expression DE (optional):** install Bioconductor `DESeq2`, `limma`, and `edgeR` for `--de-backend r`.

## Code Style

- Follow PEP 8 style guidelines
- Use type hints for function parameters and return values
- Write docstrings for all functions and classes
- Use meaningful variable and function names

## Testing

```bash
pytest tests/unit -q
```

Expression pipeline tests use the mock DE backend (no R). Full R DE is optional for local runs.

Run with coverage:
```bash
pytest --cov=orbit-ocsp tests/unit

```

## Pull Request Process

1. **Fork the repository** and create a feature branch
2. **Make your changes** following the code style guidelines
3. **Add tests** for new functionality
4. **Update documentation** if necessary
5. **Run tests** to ensure everything passes
6. **Submit a pull request** with a clear description of changes

## Reporting Issues

When reporting issues, please include:
- Python version
- Operating system
- Steps to reproduce the issue
- Expected vs actual behavior
- Any error messages or logs

## Feature Requests

For feature requests, please:
- Describe the use case
- Explain why it would be useful
- Provide examples if possible

## License

By contributing to orbit-ocsp, you agree that your contributions will be licensed under the MIT License.
