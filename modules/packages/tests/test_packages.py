from suil.testing import get_order, get_requires


def config(load, suil_context, **kwargs):
    return load('packages', 'config').Config(suil=suil_context, **kwargs)


def test_a_bare_name_means_present(load, suil_context):
    entry = config(load, suil_context, list={'tmux': None})

    assert entry.list['tmux'].ensure == 'present'


def test_present_and_absent_go_into_separate_calls(load, suil_context):
    main = load('packages')
    entry = config(load, suil_context, list={
        'tmux': {'ensure': 'present'},
        'telnet': {'ensure': 'absent'},
    })

    assert main._names(entry, wanted=True, only=None) == ['tmux']
    assert main._names(entry, wanted=False, only=None) == ['telnet']


def test_a_version_is_appended_to_the_name_for_dnf(load, suil_context):
    main = load('packages')
    entry = config(load, suil_context, list={'net-tools': {'ensure': '2.10-8.el10'}})

    assert main._names(entry, wanted=True, only=None) == ['net-tools-2.10-8.el10']


def test_only_a_package_dnf_cannot_already_see_asks_for_a_clean(load, suil_context):
    main = load('packages')
    entry = config(load, suil_context, list={
        'htop': {'ensure': '3.3.0-1.el10'},
        'tmux': None,
        'telnet': {'ensure': 'absent'},
    })
    converged = {'htop': {'ensure': '3.3.0-1.el10'}, 'tmux': {'ensure': 'present'},
                 'telnet': {'ensure': 'absent'}}

    assert main._missing(entry, None, converged) is False
    assert main._missing(entry, None, {**converged, 'htop': {'ensure': '3.2.2-1.el10'}}) is True
    assert main._missing(entry, None, {'htop': {'ensure': '3.3.0-1.el10'}}) is True
    assert main._missing(entry, {'htop'}, {'htop': {'ensure': '3.3.0-1.el10'}}) is False


def test_expected_is_the_config_shape_so_the_diff_compares_like_with_like(load, suil_context):
    main = load('packages')
    entry = config(load, suil_context, list={'tmux': None, 'telnet': {'ensure': 'absent'}})

    assert main.Packages(entry).expected() == {
        'list': {'tmux': {'ensure': 'present'}, 'telnet': {'ensure': 'absent'}}}


def test_packages_declares_repos_rather_than_relying_on_position(modules):
    # The set is installed out of the repositories that module declares.
    assert get_requires(modules['packages']) == ['repos']
    assert get_order(['packages'], modules) == ['repos', 'packages']
