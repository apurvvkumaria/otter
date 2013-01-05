"""
Tests for :mod:`otter.models.mock`
"""
import mock

from twisted.trial.unittest import TestCase

from otter.models.mock import (
    generate_entity_links, MockScalingGroup, MockScalingGroupCollection)
from otter.models.interface import NoSuchScalingGroupError, NoSuchEntityError

from otter.test.models.test_interface import (
    IScalingGroupProviderMixin,
    IScalingGroupCollectionProviderMixin)


class GenerateEntityLinksTestCase(TestCase):
    """
    Tests for :func:`generate_entity_links`
    """

    def test_default_format_for_one_link(self):
        """
        Link can be generated from just the tenant ID and entity ID.
        """
        links = generate_entity_links("1", ["1"])
        href = "http://dfw.servers.api.rackspacecloud.com/v2/1/servers/1"
        self.assertEqual(links, {
            "1": [
                {
                    "rel": "self",
                    "href": href
                }
            ]
        })

    def test_region_version_options_for_one_link(self):
        """
        Link can also be generated for a particular region and api version and
        entity type
        """
        links = generate_entity_links("1", ["1"], region="ord",
                                      api_version="1.0",
                                      entity_type="loadbalancers")
        href = ("http://ord.loadbalancers.api.rackspacecloud.com/"
                "v1.0/1/loadbalancers/1")
        self.assertEqual(links, {
            "1": [
                {
                    "rel": "self",
                    "href": href
                }
            ]
        })

    def test_creates_links_for_each_entity_id(self):
        """
        If 5 ids are passed in, 5 links are returned
        """
        links = generate_entity_links("1", [str(i) for i in range(5)])
        self.assertEqual(len(links), 5)


class MockScalingGroupTestCase(IScalingGroupProviderMixin, TestCase):
    """
    Tests for :class:`MockScalingGroup`
    """

    def setUp(self):
        """
        Create a mock group
        """
        self.tenant_id = '11111'
        self.config = {
            'name': '',
            'cooldown': 0,
            'minEntities': 0
        }
        # this is the config with all the default vals
        self.output_config = {
            'name': '',
            'cooldown': 0,
            'minEntities': 0,
            'maxEntities': None,
            'metadata': {}
        }
        self.launch_config = {
            "type": "launch_server",
            "args": {"server": {"these are": "some args"}}
        }
        self.policies = []
        self.group = MockScalingGroup(
            self.tenant_id, 1,
            {'config': self.config, 'launch': self.launch_config,
             'policies': self.policies})

    def test_view_manifest_has_all_info(self):
        """
        View manifest should return a dictionary that conforms to the JSON
        schema
        """
        result = self.validate_view_manifest_return_value()
        self.assertEqual(result, {
            'groupConfiguration': self.output_config,
            'launchConfiguration': self.launch_config,
            'scalingPolicies': {}
        })

    def test_default_view_config_has_all_info(self):
        """
        View should return a dictionary that conforms to the JSON schema (has
        all parameters even though only a few were passed in)
        """
        result = self.validate_view_config_return_value()
        self.assertEqual(result, self.output_config)

    def test_view_launch_config_returns_what_it_was_created_with(self):
        """
        The view config that is returned by the MockScalingGroup is the same
        one it was created with.  There is currently no validation for what
        goes in and hence what goes out, so just check if they are the same.
        """
        result = self.assert_deferred_succeeded(self.group.view_launch_config())
        self.assertEqual(result, self.launch_config)

    def test_add_entities(self):
        """
        The add entity utility function adds pending/active entities to the
        scaling group.  This is needed for testing view state.
        """
        active = ("1", "2", "3")
        pending = ("4", "5", "6")
        self.group.add_entities(pending=pending, active=active)

        result_pending = self.group.pending_entities.keys()
        result_pending.sort()
        result_active = self.group.active_entities.keys()
        result_active.sort()

        self.assertEqual(list(result_pending), list(pending))
        self.assertEqual(list(result_active), list(active))

    def test_view_state_returns_valid_scheme(self):
        """
        ``view_state`` returns something conforming to the scheme whether or
        not there are entities in the system
        """
        self.group.add_entities(pending=("4", "5", "6"), active=("1", "2", "3"))
        expected_active = generate_entity_links(self.tenant_id, ("1", "2", "3"))
        expected_pending = generate_entity_links(self.tenant_id, ("4", "5", "6"))
        self.group.steady_state = 6
        self.assertEquals(self.validate_view_state_return_value(), {
            'steadyState': 6,
            'active': expected_active,
            'pending': expected_pending,
            'paused': False
        })

    def test_set_steady_state_does_not_exceed_min(self):
        """
        Setting a steady state that is below the min will set the steady state
        to the min.
        """
        self.config['minEntities'] = 5
        self.group = MockScalingGroup(
            self.tenant_id, 1,
            {'config': self.config, 'launch': self.launch_config,
             'policies': self.policies})

        self.assert_deferred_succeeded(self.group.set_steady_state(1))
        self.assertEqual(self.group.steady_state, 5)

    def test_set_steady_state_does_not_exceed_max(self):
        """
        Setting a steady state that is above the max will set the steady state
        to the max.
        """
        self.config['maxEntities'] = 5
        self.group = MockScalingGroup(
            self.tenant_id, 1,
            {'config': self.config, 'launch': self.launch_config,
             'policies': self.policies})
        self.assert_deferred_succeeded(self.group.set_steady_state(10))
        state = self.validate_view_state_return_value()
        self.assertEqual(state.get('steadyState', None), 5)

    def test_set_steady_state_within_limit_succeeds(self):
        """
        Setting a steady state that is between the min and max will set the
        steady state to to the specified number.
        """
        self.assert_deferred_succeeded(self.group.set_steady_state(10))
        state = self.validate_view_state_return_value()
        self.assertEqual(state.get('steadyState', None), 10)

    def test_bounce_existing_entity_succeeds(self):
        """
        Bouncing an existing entity succeeds (and does not change the list
        view)
        """
        self.group.active_entities = {"1": [{'rel': 'self', 'href': ''}]}
        self.assertIsNone(self.assert_deferred_succeeded(
            self.group.bounce_entity("1")))
        state = self.validate_view_state_return_value()
        self.assertEqual(state.get('active', None),
                         {"1": [{'rel': 'self', 'href': ''}]})

    def test_bounce_invalid_entity_fails(self):
        """
        Bouncing an invalid valid entity fails
        """
        self.assert_deferred_failed(
            self.group.bounce_entity("1"), NoSuchEntityError)
        self.flushWarnings(NoSuchEntityError)
        state = self.validate_view_state_return_value()
        self.assertEqual(state.get('active', None), {})

    def test_update_config_overwrites_existing_data(self):
        """
        Passing in a dict only overwrites the existing dict unless the
        `partial_update` flag is passed as True
        """
        expected = {
            'cooldown': 1000,
            'metadata': {'UPDATED': 'UPDATED'},
            'minEntities': 100,
            'maxEntities': 1000,
            'name': 'UPDATED'
        }
        self.assert_deferred_succeeded(self.group.update_config(expected))
        result = self.validate_view_config_return_value()
        self.assertEqual(result, expected)

    def test_update_config_does_not_overwrite_existing_non_provided_keys(self):
        """
        If certain keys are not provided in the update dictionary and the
        `partial_update` flag is provided as True, the keys that are not
        provided are not overwritten.
        """
        self.assert_deferred_succeeded(self.group.update_config(
            {}, partial_update=True))
        result = self.validate_view_config_return_value()

        # because the returned value has the defaults filled in even if they
        # were not provided
        expected = dict(self.config)
        expected['maxEntities'] = None
        expected['metadata'] = {}
        self.assertEqual(result, expected)

    def test_update_config_min_updates_steady_state(self):
        """
        If the updated min is greater than the current steady state, the
        current steady state is set to that min
        """
        updated = {
            'name': '',
            'cooldown': 0,
            'minEntities': 5,
            'maxEntities': 10,
            'metadata': {}
        }
        self.assert_deferred_succeeded(self.group.update_config(updated))
        state = self.validate_view_state_return_value()
        self.assertEqual(state.get('steadyState', None), 5)

    def test_update_config_max_updates_steady_state(self):
        """
        If the updated max is less than the current steady state, the
        current steady state is set to that max
        """
        updated = {
            'name': '',
            'cooldown': 0,
            'minEntities': 0,
            'maxEntities': 5,
            'metadata': {}
        }
        self.assert_deferred_succeeded(self.group.set_steady_state(10))
        self.assert_deferred_succeeded(self.group.update_config(updated))
        state = self.validate_view_state_return_value()
        self.assertEqual(state.get('steadyState', None), 5)

    def test_update_config_does_not_change_launch_config(self):
        """
        When the config is updated, the launch config doesn't change.
        """
        self.assert_deferred_succeeded(self.group.update_config({
            'cooldown': 1000,
            'metadata': {'UPDATED': 'UPDATED'},
            'minEntities': 100,
            'maxEntities': 1000,
            'name': 'UPDATED'
        }))
        self.assertEqual(
            self.assert_deferred_succeeded(self.group.view_launch_config()),
            self.launch_config)

    def test_update_launch_config_overwrites_existing_data(self):
        """
        There is no partial update for the launch config.  Whatever
        `update_launch_config` is called with is what will be saved.
        """
        updated = {
            "type": "launch_server",
            "args": {"server": {"here are": "new args"}}
        }
        self.assert_deferred_succeeded(self.group.update_launch_config(updated))
        result = self.assert_deferred_succeeded(self.group.view_launch_config())
        self.assertEqual(result, updated)

    def test_update_launch_config_does_not_change_config(self):
        """
        When the launch_config is updated, the config doesn't change.
        """
        self.assert_deferred_succeeded(self.group.update_launch_config({
            "type": "launch_server",
            "args": {"server": {"here are": "new args"}}
        }))
        self.assertEqual(
            self.assert_deferred_succeeded(self.group.view_config()),
            self.output_config)


class MockScalingGroupsCollectionTestCase(IScalingGroupCollectionProviderMixin,
                                          TestCase):
    """
    Tests for :class:`MockScalingGroupCollection`
    """

    def setUp(self):
        """ Setup the mocks """
        self.collection = MockScalingGroupCollection()
        self.tenant_id = 'goo1234'
        self.config = {
            'name': 'blah',
            'cooldown': 600,
            'minEntities': 0,
            'maxEntities': 10,
            'metadata': {}
        }

    def test_list_scaling_groups_is_empty_if_new_tenant_id(self):
        """
        Listing all scaling groups for a tenant id, with no scaling groups
        because they are a new tenant id, returns an empty list
        """
        self.assertEqual(self.validate_list_return_value(self.tenant_id), [],
                         "Should start off with zero groups for tenant")

    @mock.patch('otter.models.mock.MockScalingGroup', wraps=MockScalingGroup)
    def test_create_group_with_config_and_list_scaling_groups(self, mock_sgrp):
        """
        Listing a scaling group returns a mapping of scaling group uuid to
        scaling group model, and adding another scaling group increases the
        number of scaling groups in the collection.  These are tested together
        since testing list involves putting scaling groups in the collection
        (create), and testing creation involves enumerating the collection
        (list)

        Creation of a scaling group with a 'config' parameter creates a
        scaling group with the specified configuration.
        """
        launch = {"launch": "config"}
        policies = [1, 2, 3]
        self.assertEqual(self.validate_list_return_value(self.tenant_id), [],
                         "Should start off with zero groups")
        uuid = self.assert_deferred_succeeded(
            self.collection.create_scaling_group(
                self.tenant_id, self.config, launch, policies))

        result = self.validate_list_return_value(self.tenant_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].uuid, uuid, "Group not added to collection")

        mock_sgrp.assert_called_once_with(
            self.tenant_id, uuid,
            {'config': self.config, 'launch': launch, 'policies': policies})

    @mock.patch('otter.models.mock.MockScalingGroup', wraps=MockScalingGroup)
    def test_create_group_creates_min_entities(self, mock_sgrp):
        """
        Creating a scaling group means that the minimum number of entities as
        specified by the config is created as well.
        """
        self.config['minEntities'] = 5
        launch = {"launch": "config"}
        policies = [1, 2, 3]
        mock_sgrp.return_value = mock.MagicMock(spec=MockScalingGroup)

        self.assert_deferred_succeeded(
            self.collection.create_scaling_group(
                self.tenant_id, self.config, launch, policies))

        self.assertEqual(len(mock_sgrp.return_value.add_entities.mock_calls), 1)
        self.assertEqual(
            len(mock_sgrp.return_value.add_entities.call_args[1]['pending']),
            5, "Add entities should have been called with 5 pending ids.")

    @mock.patch('otter.models.mock.MockScalingGroup', wraps=MockScalingGroup)
    def test_create_group_with_no_policies(self, mock_sgrp):
        """
        Creating a scaling group with all arguments except policies passes None
        as policies to the MockScalingGroup.
        """
        uuid = self.assert_deferred_succeeded(
            self.collection.create_scaling_group(
                self.tenant_id, self.config, {}))  # empty launch for testing

        mock_sgrp.assert_called_once_with(
            self.tenant_id, uuid,
            {'config': self.config, 'launch': {}, 'policies': None})

    def test_delete_removes_a_scaling_group(self):
        """
        Deleting a valid scaling group decreases the number of scaling groups
        in the collection
        """
        uuid = self.assert_deferred_succeeded(
            self.collection.create_scaling_group(
                self.tenant_id, self.config, {}))  # empty launch for testing

        result = self.validate_list_return_value(self.tenant_id)
        self.assertEqual(len(result), 1, "Group not added correctly")

        self.assert_deferred_succeeded(
            self.collection.delete_scaling_group(self.tenant_id, uuid))

        result = self.validate_list_return_value(self.tenant_id)
        self.assertEqual(result, [], "Group not deleted from collection")

    def test_delete_scaling_group_fails_if_scaling_group_does_not_exist(self):
        """
        Deleting a scaling group that doesn't exist raises a
        :class:`NoSuchScalingGroupError` exception
        """
        deferred = self.collection.delete_scaling_group(self.tenant_id, 1)
        self.assert_deferred_failed(deferred, NoSuchScalingGroupError)

    def test_get_scaling_group_returns_mock_scaling_group(self):
        """
        Getting valid scaling group returns a MockScalingGroup whose methods
        work.
        """
        uuid = self.assert_deferred_succeeded(
            self.collection.create_scaling_group(
                self.tenant_id, self.config, {}))  # empty launch for testing
        group = self.validate_get_return_value(self.tenant_id, uuid)

        self.assertTrue(isinstance(group, MockScalingGroup),
                        "group is {0!r}".format(group))

        for method in ('view_config', 'view_launch_config', 'view_state'):
            self.assert_deferred_succeeded(getattr(group, method)())

        self.assert_deferred_succeeded(group.update_config({
            'name': '1', 'minEntities': 0, 'cooldown': 0, 'maxEntities': None,
            'metadata': {}
        }))
        self.assert_deferred_succeeded(group.set_steady_state(1))

        group.active_entities = ["1"]
        self.assert_deferred_succeeded(group.bounce_entity("1"))

    def test_get_scaling_group_works_but_methods_do_not(self):
        """
        Getting a scaling group that doesn't exist returns a MockScalingGropu
        whose methods will raise :class:`NoSuchScalingGroupError` exceptions.
        """
        group = self.validate_get_return_value(self.tenant_id, 1)
        self.assertTrue(isinstance(group, MockScalingGroup),
                        "group is {0!r}".format(group))

        for method in ('view_config', 'view_launch_config', 'view_state'):
            self.assert_deferred_failed(getattr(group, method)(),
                                        NoSuchScalingGroupError)

        self.assert_deferred_failed(group.update_config(
            {
                'name': '1',
                'minEntities': 0,
                'cooldown': 0,
                'maxEntities': None,
                'metadata': {}
            }), NoSuchScalingGroupError)

        self.assert_deferred_failed(group.set_steady_state(1),
                                    NoSuchScalingGroupError)
        self.assert_deferred_failed(group.bounce_entity("1"),
                                    NoSuchScalingGroupError)
