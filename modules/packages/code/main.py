from pyinfra.operations import dnf

from suil.sdk import Module

from .config import Config


def _missing(config: Config, only, reported: dict) -> bool:
    for name, spec in config.list.items():
        if only is not None and name not in only:
            continue

        ensure = spec.ensure if spec else 'present'

        if ensure != 'absent' and (reported.get(name) or {}).get('ensure') != ensure:
            return True

    return False


def _names(config: Config, wanted: bool, only) -> list[str]:
    names = []

    for name, spec in sorted(config.list.items()):
        if only is not None and name not in only:
            continue

        ensure = spec.ensure if spec else 'present'

        if wanted and ensure != 'absent':
            names.append(name if ensure == 'present' else f'{name}-{ensure}')
        elif not wanted and ensure == 'absent':
            names.append(name)

    return names


class Packages(Module[Config]):

    def deploy(self, facts: dict, force: bool) -> None:
        diff = self.diff_configs(self.expected(), facts)

        if not (diff or force):
            return

        only = self.diff_names(None if force else diff, 'list')

        # One transaction each way. Looping the operation per package costs one dnf
        # transaction per entry, which is what the ansible role was fixed to stop.
        if present := _names(self.config, wanted=True, only=only):
            dnf.packages(
                name=f'Install {len(present)} base packages',
                packages=present,
                present=True,
                # Cached metadata does not know a freshly published pin until it expires.
                clean=_missing(self.config, only, facts.get('list') or {}),
            )

        if absent := _names(self.config, wanted=False, only=only):
            dnf.packages(
                name=f'Remove {len(absent)} packages',
                packages=absent,
                present=False,
            )

    def expected(self) -> dict:
        return {
            'list': {name: {'ensure': (spec.ensure if spec else 'present')}
                     for name, spec in self.config.list.items()},
        }
