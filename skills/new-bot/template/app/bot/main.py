from utilbots_core.bot import UtilBot, run

from .. import models  # noqa: F401  (register tables)
from .cogs import MainCog


class __CLASS__(UtilBot):
    def __init__(self):
        super().__init__(status_text="/plan")
        self.add_cog(MainCog(self))


def main():
    run(__CLASS__)


if __name__ == "__main__":
    main()
