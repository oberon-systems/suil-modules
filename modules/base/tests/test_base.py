from suil.testing import get_order, get_requires


def test_base_expands_in_list_order(modules):
    assert get_order(['base'], modules) == [
        'hostname', 'selinux', 'repos', 'packages', 'accounts', 'ssh', 'nftables', 'base']


def test_nftables_is_last_and_repos_precedes_packages(modules):
    order = get_order(['base'], modules)

    assert order.index('nftables') > order.index('packages')
    assert order.index('accounts') < order.index('ssh')
    assert order.index('repos') < order.index('packages')


def test_base_carries_no_code_of_its_own(modules):
    # A meta module is its requires list and nothing else.
    assert get_requires(modules['base'])
    assert not (modules['base'].path / 'code').exists()
