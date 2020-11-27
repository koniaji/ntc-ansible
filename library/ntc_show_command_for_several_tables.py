#!/usr/bin/env python

# Copyright 2015 Jason Edelman <jason@networktocode.com>
# Network to Code, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

DOCUMENTATION = '''
---

'''
EXAMPLES = '''

'''

import os.path
import socket

from ansible import __version__ as ansible_version
if float(ansible_version[:3]) < 2.4:
    raise ImportError("Ansible versions < 2.4 are not supported")

HAS_NTC_TEMPLATES = True
try:
    from ntc_templates.parse import _get_template_dir as ntc_get_template_dir
except:
    HAS_NTC_TEMPLATES = False

HAS_NETMIKO = True
try:
    from netmiko import ConnectHandler
except:
    HAS_NETMIKO = False

HAS_TEXTFSM = True
try:
    import textfsm
except:
    try:
        import textfsm
    except:
        HAS_TEXTFSM = False

HAS_TRIGGER = True
try:
    from trigger.cmds import Commando
except:
    HAS_TRIGGER = False

if HAS_NTC_TEMPLATES:
    NTC_TEMPLATES_DIR = ntc_get_template_dir()
else:
    NTC_TEMPLATES_DIR = 'ntc_templates/templates'

def parse(template, raw_data):
    re_table = textfsm.TextFSM(open(template))
    data = re_table.ParseText(raw_data)

    ar = []
    for item in data:
        obj = {}
        for key, value in enumerate(item):
            obj[re_table.header[key]] = value
        ar.append(obj)

    return ar

def merge_by_attr(attrs, list1, list2):
    merged = []
    for item1 in list1:
        for item2 in list2:
            flag = True
            for attr in attrs:
                if item1[attr] != item2[attr]:
                    flag = False
                    break
            if flag:
                item1.update(item2)
                merged.append(item1)
                break

    return merged

def parse_raw_output(rawoutput, module):
    res1 = parse(module.params['first_template_file'], rawoutput)
    res2 = parse(module.params['second_template_file'], rawoutput)

    return merge_by_attr(['ONT_ID', 'PORT'], res1, res2)

def main():
    connection_argument_spec = dict(
        connection=dict(
            choices=[
                'ssh',
                'offline',
                'netmiko_ssh',
                'trigger_ssh',
                'netmiko_telnet',
                'telnet'
            ],
            default='netmiko_ssh',
        ),
        platform=dict(required=False),
        host=dict(required=False),
        port=dict(required=False),
        username=dict(required=False, type='str'),
        password=dict(required=False, type='str', no_log=True),
        secret=dict(required=False, type='str', no_log=True),
        use_keys=dict(required=False, default=False, type='bool'),
        trigger_device_list=dict(type='list', required=False),
        delay=dict(default=1, required=False),
        global_delay_factor=dict(default=1, required=False),
        key_file=dict(required=False, default=None),
        optional_args=dict(required=False, type='dict', default={}),
        connection_args=dict(required=False, type='dict', default={}),
    )
    base_argument_spec = dict(
        file=dict(required=False),
        local_file=dict(required=False),
        first_template_file=dict(required=True),
        second_template_file=dict(required=True),
        use_templates=dict(required=False, default=True, type='bool'),
        command=dict(required=True),
    )
    argument_spec = base_argument_spec
    argument_spec.update(connection_argument_spec)
    argument_spec["provider"] = dict(required=False, type="dict", options=connection_argument_spec)

    module = AnsibleModule(
        argument_spec=argument_spec,
        mutually_exclusive=(
            ['host', 'trigger_device_list'],
        ),
        supports_check_mode=False
    )

    provider = module.params['provider'] or {}

    # allow local params to override provider
    for param, pvalue in provider.items():
        if module.params.get(param) != False:
            module.params[param] = module.params.get(param) or pvalue

    if not HAS_TEXTFSM:
        module.fail_json(msg='This module requires TextFSM')

    connection = module.params['connection']
    platform = module.params['platform']
    device_type = platform.split('-')[0]
    raw_file = module.params['file']
    local_file = module.params['local_file']
    command = module.params['command']
    username = module.params['username']
    password = module.params['password']
    secret = module.params['secret']
    use_templates = module.params['use_templates']
    use_keys = module.params['use_keys']
    key_file = module.params['key_file']
    delay = int(module.params['delay'])
    global_delay_factor = int(module.params['global_delay_factor'])
    trigger_device_list = module.params['trigger_device_list']
    optional_args = module.params['optional_args']
    connection_args = module.params['connection_args']
    host = module.params['host']

    if (connection in ['ssh', 'netmiko_ssh', 'netmiko_telnet', 'telnet'] and
            not module.params['host']):
        module.fail_json(msg='specify host when connection='
                             'ssh/netmiko_ssh/netmiko_telnet')

    if connection in ['netmiko_telnet', 'telnet'] and platform != 'cisco_ios':
        module.fail_json(msg='only cisco_ios supports '
                             'telnet/netmiko_telnet connection')

    if platform == 'cisco_ios' and connection in ['netmiko_telnet', 'telnet']:
        device_type = 'cisco_ios_telnet'

    if module.params['port']:
        port = int(module.params['port'])
    else:
        if device_type == 'cisco_ios_telnet':
            port = 23
        else:
            port = 22

    argument_check = { 'platform': platform }
    if connection != 'offline':
        argument_check['username'] = username
        argument_check['password'] = password
        argument_check['host'] = host
        if not host and not trigger_device_list:
            module.fail_json(msg='specify host or trigger_device_list based on connection')

    for key, val in argument_check.items():
        if val is None:
            module.fail_json(msg=str(key) + " is required")

    if connection == 'offline' and not raw_file:
        module.fail_json(msg='specifiy file if using connection=offline')

    rawtxt = ''
    if connection in ['ssh', 'netmiko_ssh', 'netmiko_telnet', 'telnet']:
        if not HAS_NETMIKO:
            module.fail_json(msg='This module requires netmiko.')

        device_args = dict(
            device_type=device_type,
            ip=host,
            port=port,
            username=username,
            password=password,
            secret=secret,
            use_keys=use_keys,
            key_file=key_file,
            global_delay_factor=global_delay_factor
        )
        if connection_args:
            device_args.update(connection_args)
        device = ConnectHandler(**device_args)
        if secret:
            device.enable()

        rawtxt = device.send_command_timing(command, delay_factor=delay)

    elif connection == 'trigger_ssh':
        if not HAS_TRIGGER:
            module.fail_json(msg='This module requires trigger.')
        kwargs = {}
        kwargs['production_only'] = False
        kwargs['force_cli'] = True
        if optional_args:
            module.deprecate(
                msg="optional_args is deprecated in favor of connection_args."
            )
            kwargs.update(optional_args)
        if connection_args:
            kwargs.update(connection_args)

        if host:
            commando = Commando(devices=[host], commands=[command],
                                creds=(username, password), **kwargs)
            commando.run()
            rawtxt = commando.results[host][command]
        elif trigger_device_list:
            commando = Commando(devices=trigger_device_list, commands=[command],
                                creds=(username, password), **kwargs)
            commando.run()

    elif connection == 'offline':
        with open(raw_file, 'r') as data:
            rawtxt = data.read()

    if local_file:
        with open(local_file, 'w') as f:
            f.write(rawtxt)

    results = {}
    results['response'] = []
    results['response_list'] = []

    if use_templates:
        if rawtxt:
            results['response'] = parse_raw_output(rawtxt, module)
        elif trigger_device_list:
            results['response_list'] = parse_raw_output(commando.results, module)
    elif rawtxt:
        results['response'] = [rawtxt]
    elif trigger_device_list:
        results['response'] = [commando.results]

    module.exit_json(**results)


from ansible.module_utils.basic import *
if __name__ == "__main__":
    main()