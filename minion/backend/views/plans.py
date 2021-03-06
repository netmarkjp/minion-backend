#!/usr/bin/env python

import calendar
import datetime
import importlib
import uuid

from flask import jsonify, request

import minion.backend.utils as backend_utils
import minion.backend.tasks as tasks
from minion.backend.app import app
from minion.backend.views.base import api_guard, plans, plugins


def sanitize_plan(plan):
    if plan.get('_id'):
        del plan['_id']
    for field in ('created',):
        if plan.get(field) is not None:
            plan[field] = calendar.timegm(plan[field].utctimetuple())
    return plan

def _split_plugin_class_name(plugin_class_name):
    e = plugin_class_name.split(".")
    return '.'.join(e[:-1]), e[-1]

def _import_plugin(plugin_class_name):
    package_name, class_name = _split_plugin_class_name(plugin_class_name)
    plugin_module = importlib.import_module(package_name, class_name)
    return getattr(plugin_module, class_name)

def _check_plan_workflow(workflow):
    """ Ensure plan workflow contain valid structure. """
    if not all(isinstance(plugin, dict) for plugin in workflow):
        return False
    required_fields = set(('plugin_name', 'configuration', 'description'))
    #
    if len(workflow) == 0:
        return False
    for plugin in workflow:
        # test whether every field in required_fields is in plugin keys
        if not required_fields.issubset(set(plugin.keys())):
            return False
        if not isinstance(plugin['configuration'], dict):
            return False
        try:
            _import_plugin(plugin['plugin_name'])
        except (AttributeError, ImportError):
            return False
    return True

def _check_plan_exists(plan_name):
    return plans.find_one({'name': plan_name}) is not None

# API Methods to manage plans

#
# Return a list of available plans. Plans are global and not
# limited to a specific user.
#
#  GET /plans
#
# Returns an array of plan:
#
#  { "success": true,
#    "plans": [ { "description": "Run an nmap scan",
#                 "name": "nmap" },
#               ... ] }
#

@app.route("/plans", methods=['GET'])
@api_guard
def get_plans():
    def _plan_description(plan):
        return { 
            'description': plan['description'], 
            'name': plan['name'], 
            'workflow': plan['workflow'],
            'created' : plan['created'] }
    
    return jsonify(success=True, 
    plans=[sanitize_plan(_plan_description(plan)) for plan in plans.find()])

#
# Delete an existing plan
#
#  DELETE /plans/<plan_name>
#

@app.route('/plans/<plan_name>', methods=['DELETE'])
@api_guard
def delete_plan(plan_name):
    plan = plans.find_one({'name': plan_name})
    if not plan:
        return jsonify(success=False, reason='no-such-plan')
    # Remove the plan
    plans.remove({'name': plan_name})
    return jsonify(success=True)

#
# Create a new plan
#

@app.route("/plans", methods=['POST'])
@api_guard('application/json')
def create_plan():
    plan = request.json

    # Verify incoming plan
    if plans.find_one({'name': plan['name']}) is not None:
        return jsonify(success=False, reason='plan-already-exists')

    if not _check_plan_workflow(plan['workflow']):
        return jsonify(success=False, reason='invalid-plan-exists')

    # Create the plan
    new_plan = { 'name': plan['name'],
                 'description': plan['description'],
                 'workflow': plan['workflow'],
                 'created': datetime.datetime.utcnow() }
    plans.insert(new_plan)

    # Return the new plan
    plan = plans.find_one({"name": plan['name']})
    if not plan:
        return jsonify(success=False)
    return jsonify(success=True, plan=sanitize_plan(plan))

#
# Update a plan
#

@app.route('/plans/<plan_name>', methods=['POST'])
@api_guard
def update_plan(plan_name):
    new_plan = request.json
    # Find the existing plan
    old_plan = plans.find_one({'name': plan_name})
    if old_plan is None:
        return jsonify(success=False, reason='unknown-plan')

    if not _check_plan_workflow(new_plan['workflow']):
        return jsonify(success=False, reason='invalid-plan')

    # Update the plan
    changes = {}
    if 'description' in new_plan:
        changes['description'] = new_plan['description']
    if 'workflow' in new_plan:
        changes['workflow'] = new_plan['workflow']
    plans.update({'name': plan_name}, {'$set': changes})
    # Return the plan
    plan = plans.find_one({"name": plan_name})
    return jsonify(success=True, plan=sanitize_plan(plan))


#
# Return a single plan description. Takes the plan name.
#
#  GET /plans/:plan_name
#
# Returns a JSON structure that contains the complete plan
#
#  { "success": true,
#    "plan": { "description": "Run an nmap scan",
#               "name": "nmap",
#               "workflow": [ { "configuration": {},
#                               "description": "Run the NMAP scanner.",
#                               "plugin": { "version": "0.2",
#                                           "class": "minion.plugins.nmap.NMAPPlugin",
#                                           "weight": "light",
#                                           "name": "NMAP" } } ] }
#

@app.route("/plans/<plan_name>", methods=['GET'])
@api_guard
def get_plan(plan_name):
    plan = plans.find_one({"name": plan_name})
    if not plan:
        return jsonify(success=False, reason='no-such-plan')
    # Fill in the details of the plugin
    for step in plan['workflow']:
        plugin = plugins.get(step['plugin_name'])
    return jsonify(success=True, plan=sanitize_plan(plan))

