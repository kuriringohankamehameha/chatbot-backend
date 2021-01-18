from collections import defaultdict

def exclude_field(node, exclude_list):
    for key in exclude_list:
        if key in node:
            del node[key]
    return node

# clean up the function once it is final(All test cases are covered)
def parse_json(obj):
    """
        function that converts the bot_full_json to bot_data_json
        while saving the bot.
    """
    node_dict = dict()
    variable_dict = dict()
    lead_dict = dict()

    options = dict() # For list of user defined options

    has_init_component = False
    subscribe_email = False

    source_target = defaultdict(list)
    sourcePort_target = dict()
    target_port_name = defaultdict(list)

    exclude_list = ['primaryText', 'secondaryText', 'type', 'selected', 'locked', 'portOpt']

    # mapping source to target, sourcePort to target, nodeData to key, target to port_name
    for layer in obj['layers']:
        for key in layer['models'].keys():
            model_node = layer['models'][key]
            if 'source' in model_node:
                source_target[model_node['source']].append(model_node['target'])
                sourcePort_target[model_node['sourcePort']] = model_node['target']
            elif 'ports' in model_node:
                for port in model_node['ports']:
                    if port['in'] is False:
                        try:
                            target_port_name[sourcePort_target[port['id']]].append(port['name'])
                        except KeyError:
                            try:
                                port_name = port['name']
                            except KeyError:
                                raise ValueError(f"One of the ports doesn't have 'name' property set")
                            raise ValueError(f"Target Port to Source Port mapping couldn't be done for the Port {port_name}")
                node_dict[key] = model_node['nodeData']

    # modifying the node_dict as per need
    for key in node_dict.keys():
        node = node_dict[key]
        if 'variable' in node:
            variable_dict[node['variable']] = ""
        
        if 'isLeadField' in node:
            # Check for lead fields
            if 'variable' not in node:
                # 'isLeadField' MUST go hand in hand with 'variable'
                if node['isLeadField'] == True:
                    raise ValueError("Node has isLeadField, but does not have a variable")
            if node['isLeadField'] == True:
                lead_dict[node['variable']] = ""
        
        if node['nodeType'] == 'INIT':
            # We need the INIT component to start the flow
            has_init_component = True
        
        if node['nodeType'] == 'AGENT_TRANSFER':
            # Check if admin wants to subscribe
            if 'team' in node_dict[key]:
                node_dict[key]['team'] = node['team']
                if 'subscribeEmail' in node and node['subscribeEmail'] == True:
                    subscribe_email = True
                
        if node['nodeType'] == 'TEAM_TRANSFER':
            if 'team' in node_dict[key]:
                node_dict[key]['team'] = node['team']
                if 'subscribeEmail' in node and node['subscribeEmail'] == True:
                    subscribe_email = True
        
        if node['nodeType'] == 'WEBHOOK':
            # Webhook component
            required_constaints = {
                "webhookUrl": [],
                "requestType": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            }
            optional_fields = ["requestHeaders", "queryParams", "requestBody", "routingComponent"]

            for field in required_constaints:
                if field not in node:
                    raise ValueError(f"Need to provide {field} in the Webhook component")

                if required_constaints[field] != [] and node[field] not in required_constaints[field]:
                    raise ValueError(f"Field {field} can only have one of {', '.join(required_constaint for required_constaint in required_constaints[field])}")

                node_dict[key][field] = node[field]
            
            for field in optional_fields:
                if field not in node:
                    node_dict[key][field] = None
                else:
                    node_dict[key][field] = node[field]

        if node['nodeType'] == 'YES_NO' or node['nodeType'] == 'MULTI_CHOICE' or node['nodeType'] == 'WHATSAPP_TEMPLATE':
            print(node['nodeType'])
            buttons = []
            for portOpt in node['portOpt']:
                if portOpt['linkType'] == 'out':
                    for target in source_target[key]:
                        for port_name in target_port_name[target]:
                            if port_name == portOpt['name']:
                                button_target = target
                    buttons.append(
                        {
                            'text':portOpt['componentProps']['text'],
                            'targetId':button_target
                        }
                    )
                    node['buttons'] = buttons
                else:
                    node['input'] = portOpt['name']
        else:
            
            if len(source_target[key])==0:
                node['targetId'] = ""
            else:
                node['targetId'] = source_target[key][0]

        node = exclude_field(node, exclude_list)
    
    if has_init_component == False:
        # Error. Must have INIT
        raise ValueError("Bot JSON must have an INIT component")
    
    options['subscribe_email'] = subscribe_email

    return node_dict, variable_dict, lead_dict, options
