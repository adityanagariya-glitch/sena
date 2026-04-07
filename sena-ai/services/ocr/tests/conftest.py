# OCR Service Test Configuration (services/ocr/tests/conftest.py)
#
# Purpose: pytest configuration for OCR service tests
#
# Functionality:
# - Adds service src and shared src to Python path
# - Allows test files to import from both modules without installation
# - Path setup: ../src (service) and ../../shared/src (shared library)
#
# Test discovery:
# - pytest automatically runs conftest.py before collecting tests
# - Fixtures and configuration defined here apply to all tests in the directory
