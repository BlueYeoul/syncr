"""syncr - Local → Server file sync tool."""
__version__ = "0.1.0"
 
 
def main():
    from syncr.cli import main as _main
    _main()
 