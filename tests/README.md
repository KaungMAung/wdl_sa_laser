# Offline verification harness

Run from the repository root:

```text
python -m unittest discover -s tests -v
```

The tests use temporary SQLite databases and in-memory fake SQL, PLC, and
recipe services. They do not require a PLC, SQL Server, credentials, or
pycomm3 communication.

