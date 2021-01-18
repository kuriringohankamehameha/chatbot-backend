import json
import uuid
from collections import defaultdict
from copy import deepcopy

from decouple import config

from .lexer import Lexer, LexerError, Token

try:
    WEBHOOK_TIMEOUT = float(config('WEBHOOK_TIMEOUT'))
except:
    WEBHOOK_TIMEOUT = 20 # Default is 20 seconds


class BotJSONParseError(Exception):
    def __init__(self, msg):
        self.msg = msg


class BotJSONParser():
    def __init__(self, restricted_variables=None):
        self.node_dict = dict()
        self.variable_dict = dict()
        self.variable_types = dict()
        self.required_variable_types = ['int', 'float', 'string', 'datetime', 'bool']
        self.type_expression_dict = {'NUMBER': 'int', 'STRING': 'string', 'DATE': 'datetime', 'TIME': 'datetime', 'FLOAT': 'float'}
        self.lead_dict = dict()

        self.options = dict() # For list of user defined options

        self.has_init_component = False
        self.subscribe_email = False

        self.init_component_id = None

        self.source_target = defaultdict(list)
        self.target_source = defaultdict(list)
        self.sourcePort_target = dict()
        self.targetPort_source = dict()
        self.target_port_name = defaultdict(list)
        self.source_port_name = defaultdict(list)
        self.visited_nodes = set()
        self.initialized_variables = set()

        self.restricted_variables = restricted_variables

        self.exclude_list = ['primaryText', 'secondaryText', 'type', 'selected', 'locked', 'portOpt']
    

    def message_to_variable_tokenizer(self, msg):
        if isinstance(msg, str):
            tokens = msg.split(' ')
            return list(filter(lambda x: x.startswith("@"), tokens))
        else:
            return list()
    

    def construct_restricted_variables(self):
        if self.restricted_variables in [None, {}]:
            self.restricted_variables = {}
            return
        
        if not isinstance(self.restricted_variables, list):
            raise BotJSONParseError(f"Invalid Payload Format: restricted_variables field must be a list")

        restricted_variables = {}
        
        try:
            for instance in self.restricted_variables:
                variable = instance['variable']
                value = instance.get('value', '')
                is_lead = instance.get('is_lead', False)
                restricted_variables[variable] = value
                self.variable_dict[variable] = value
                if is_lead == True:
                    self.lead_dict[variable] = ""
            self.restricted_variables = restricted_variables
        except Exception as ex:
            print(ex)
            raise BotJSONParseError(f"Error when constructing restricted_variables field")
    

    def parse_json(self, bot_json):
        self.map_input_components(bot_json)

        self.construct_restricted_variables()

        # modifying the node_dict as per need
        for key in self.node_dict.keys():
            node = self.node_dict[key]
            
            self.set_variable_dict(node)
            self.set_lead_dict(node)
            self.parse_node(node, key)
        
        if self.has_init_component == False:
            # Error. Must have INIT
            raise BotJSONParseError("Bot JSON must have an INIT component")
        
        self.options['subscribe_email'] = self.subscribe_email

        return self.node_dict, self.variable_dict, self.lead_dict, self.options


    def parse_node(self, node, key):
        if node['nodeType'] == 'INIT':
            # We need the INIT component to start the flow and initialize all variables
            self.has_init_component = True
            self.init_component_id = key
            node = self.initialize_variables(node, key)
        
        elif node['nodeType'] == 'AGENT_TRANSFER':
            node = self.parse_agent_takeover_component(node, key)
                
        elif node['nodeType'] == 'TEAM_TRANSFER':
            node = self.parse_team_takeover_component(node, key)
        
        elif node['nodeType'] == 'WEBHOOK':
            node = self.parse_webhook_component(node, key)

        elif node['nodeType'] == 'YES_NO' or node['nodeType'] == 'MULTI_CHOICE' or node['nodeType']=='WHATSAPP_TEMPLATE':
            node = self.parse_multiple_choice_node(node, key)
        
        elif node['nodeType'] == 'IF_ELSE':
            node = self.parse_conditional_node(node, key)

        elif node['nodeType'] == 'SET_VARIABLE':
            node = self.parse_set_variable_node(node, key)
        
        elif node['nodeType'] == 'GOAL':
            node = self.parse_goal_component(node, key)

        elif node['nodeType'] == 'SET_VARIABLE_BETA':
            node = self.parse_set_variable_node_beta(node, key)
        
        self.node_dict[key] = node

        node = self.assign_targetid(node, key)
        
        # Now exclude useless fields
        self.node_dict[key] = self.exclude_field(node)

        return


    def map_input_components(self, bot_json):
        # mapping source to target, sourcePort to target, nodeData to key, target to port_name
        # Out to In (Target to Source Mapping)
        for layer in bot_json['layers']:
            for key in layer['models'].keys():
                model_node = layer['models'][key]
                if 'source' in model_node:
                    self.source_target[model_node['source']].append(model_node['target'])
                    self.sourcePort_target[model_node['sourcePort']] = model_node['target']
                    self.target_source[model_node['target']].append(model_node['source'])
                    self.targetPort_source[model_node['targetPort']] = model_node['source']
                elif 'ports' in model_node:
                    for port in model_node['ports']:
                        if port['in'] == False:
                            # Output Port
                            try:
                                self.target_port_name[self.sourcePort_target[port['id']]].append(port['name'])
                            except KeyError:
                                try:
                                    port_name = port['name']
                                except KeyError:
                                    if ('nodeData' not in model_node) or ('nodeType' not in model_node['nodeData']):
                                        raise BotJSONParseError(f"One of the ports doesn't have 'name' property set")
                                    else:
                                        raise BotJSONParseError(f"{model_node['nodeData']['nodeType'].capitalize()} component does not have the 'name' property set")
                                if ('nodeData' not in model_node) or ('nodeType' not in model_node['nodeData']):
                                    pass
                                    # raise BotJSONParseError(f"Target Port to Source Port mapping couldn't be done for the Port {port_name}")
                                else:
                                    pass
                                    # raise BotJSONParseError(f"{model_node['nodeData']['nodeType'].capitalize()} component is not fully connected")
                        else:
                            # Input Port
                            try:
                                self.source_port_name[self.targetPort_source[port['id']]].append(port['name'])
                            except KeyError:
                                try:
                                    port_name = port['name']
                                except KeyError:
                                    if ('nodeData' not in model_node) or ('nodeType' not in model_node['nodeData']):
                                        raise BotJSONParseError(f"One of the ports doesn't have 'name' property set")
                                    else:
                                        raise BotJSONParseError(f"{model_node['nodeData']['nodeType'].capitalize()} component does not have the 'name' property set")
                                if ('nodeData' not in model_node) or ('nodeType' not in model_node['nodeData']):
                                    pass
                                    # raise BotJSONParseError(f"Target Port to Source Port mapping couldn't be done for the Port {port_name}")
                                else:
                                    pass
                                    # raise BotJSONParseError(f"{model_node['nodeData']['nodeType'].capitalize()} input component is not connected")
                    self.node_dict[key] = model_node['nodeData']


    def set_variable_dict(self, node, value="", multiple=False, field=None):
        if multiple == False:
            if 'variable' in node:
                variable = node['variable']
                
                if variable in self.restricted_variables:
                    raise BotJSONParseError(f"Variable {variable} is a restricted variable and cannot be manually set by you")

                self.variable_dict[variable] = value
            
                if 'variableType' in node:
                    if node['variableType'] not in self.required_variable_types:
                        raise BotJSONParseError(f"Variable of {node['nodeType']} component must have a Type of one of {self.required_variable_types}")
                    self.variable_types[node['variable']] = node['variableType']
                else:
                    self.variable_types[node['variable']] = 'string'
        else:
            for inode in node[field]:
                self.set_variable_dict(inode)


    def set_lead_dict(self, node, multiple=False, field=None):
        if multiple == False:
            if 'isLeadField' in node:
                # Check for lead fields
                if 'variable' not in node:
                    # 'isLeadField' MUST go hand in hand with 'variable'
                    if node['isLeadField'] == True:
                        raise BotJSONParseError("Node has isLeadField, but does not have a variable")
                if node['isLeadField'] == True:
                    self.lead_dict[node['variable']] = ""
        else:
            for inode in node[field]:
                self.set_lead_dict(inode)


    def initialize_variables(self, node, key):
        if 'variables' not in node:
            pass
        else:
            # Initialize all variables
            if isinstance(node['variables'], dict):
                for variable in node['variables']:
                    self.variable_dict[variable] = ""
                    if node['variables'][variable] == True:
                        self.lead_dict[variable] = ""
        return node


    def exclude_field(self, node):
        for key in self.exclude_list:
            if key in node:
                del node[key]
        return node
    

    def validate(self, node, key, required_constaints={}, optional_constraints={}, toggles={}):
        validated_data = {}

        for field in required_constaints:
            if field not in node:
                raise BotJSONParseError(f"Need to provide {field} in the {self.node_dict[key]['nodeType']} component")

            if required_constaints[field] is not None:
                status, content, err = required_constaints[field](node[field])
                if not status:
                    raise BotJSONParseError(f"Error validating field {field}: {err}")

            validated_data[field] = content

        for field in optional_constraints:
            if toggles != {} and field not in toggles:
                raise BotJSONParseError(f"Optional field {field} must have a 'customize{field}' toggle")
            if (field not in node) or (field in node and ((toggles is None) or (field not in toggles) or (toggles[field] in node and node[toggles[field]] == False))):
                validated_data[field] = None
                continue
            else:
                if optional_constraints[field] is not None:
                    status, content, err = optional_constraints[field](node[field])
                    if not status:
                        raise BotJSONParseError(f"Error validating field {field}: {err}")
                validated_data[field] = content
        
        return validated_data


    def parse_agent_takeover_component(self, node, key):
        # Check if admin wants to subscribe
        if 'team' in self.node_dict[key]:
            self.node_dict[key]['team'] = node['team']
            if 'subscribeEmail' in node and node['subscribeEmail'] == True:
                self.subscribe_email = True
        return node


    def parse_team_takeover_component(self, node, key):
        # Check if admin wants to subscribe
        if 'team' in self.node_dict[key]:
            self.node_dict[key]['team'] = node['team']
            if 'subscribeEmail' in node and node['subscribeEmail'] == True:
                self.subscribe_email = True
        return node


    def parse_webhook_component(self, node, key):
        # Webhook component
        required_constaints = {
            "id": lambda nodeId: (True, nodeId, None,) if nodeId is not None else (False, None, "Invalid node ID",),
            "webhookUrl": lambda webhookUrl: (True, webhookUrl, None,) if webhookUrl.startswith(('http://', 'https://',)) else (False, None, "Invalid WebHook URL",),
            "requestType": lambda requestType: (True, requestType, None,) if requestType in ["GET", "POST", "PUT", "PATCH", "DELETE"] else (False, None, "Invalid request type",),
            "blocking": lambda blocking: (True, blocking, None,) if blocking in [True, False] else (False, None, "'blocking' needs to be a boolean",),
            "routing": lambda routing: (True, routing, None,) if isinstance(routing, dict) and 'default' in routing else (False, None, "'routing' component is invalid",),
        }
        optional_constraints = {
            "requestHeaders": lambda requestHeaders: (True, requestHeaders, None,) if isinstance(requestHeaders, dict) else (False, None, "Invalid request headers",),
            "queryParams": lambda queryParams: (True, queryParams, None,) if isinstance(queryParams, dict) else (False, None, "Invalid query params",),
            "requestBody": lambda requestBody: (True, requestBody, None,) if isinstance(requestBody, dict) else (False, None, "Invalid request body",),
            "responseBody": lambda responseBody: (True, responseBody, None,) if isinstance(responseBody, dict) else (False, None, "Invalid response body",),            
            "timeout": lambda timeout: (True, self.set_webhook_timeout(timeout), None,) if (self.set_webhook_timeout(timeout) is not None) else (False, None, f"Invalid timeout value. Must lie between 0 to {WEBHOOK_TIMEOUT} seconds"),
        }
        toggles = {
            param: "customize" + param for param in optional_constraints
        }

        # First parse the Choices
        self.node_dict[key] = self.parse_multiple_choice_node(node, key, super_component='webhook')

        validated_data = self.validate(node, key, required_constaints=required_constaints, optional_constraints=optional_constraints, toggles=toggles)

        self.node_dict[key] = validated_data
        
        return node


    def parse_multiple_choice_node(self, node, key, super_component=None):
        buttons = []
        default_target = ""
        for portOpt in node['portOpt']:
            if portOpt['linkType'] == 'out':
                for target in self.source_target[key]:
                    for port_name in self.target_port_name[target]:
                        if port_name == portOpt['name']:
                            button_target = target
                try:
                    buttons.append(
                        {
                            'text': portOpt['componentProps']['text'],
                            'targetId': button_target
                        }
                    )
                except:
                    buttons.append(
                        {
                            'text': portOpt['componentProps']['text'],
                            'targetId': default_target
                        }
                    )
                node['buttons'] = buttons
            else:
                node['input'] = portOpt['name']
        
        node = self.parse_supercomponent(node, key, 'multiple_choice', super_component, props={'buttons': buttons})

        return node
    

    def parse_conditional_node(self, node, key, super_component=None):
        index = 0
        default_target = ""
        for portOpt in node['portOpt']:
            if portOpt['linkType'] == 'out':
                for target in self.source_target[key]:
                    for port_name in self.target_port_name[target]:
                        if port_name == portOpt['name']:
                            button_target = target
                try:
                    node['conditions'][index]['targetId'] = button_target
                except:
                    node['conditions'][index]['targetId'] = default_target
                index+=1
            else:
                node['input'] = portOpt['name']
        

        node = self.parse_supercomponent(node, key, 'conditional', super_component, props={})

        return node
    

    def parse_set_variable_node(self, node, key):
        required_constaints = {
            "variableList": lambda variableList: (True, variableList, None,) if isinstance(variableList, list) and ("variable" in variableList[0] and isinstance(variableList[0]["variable"], str) and "isLeadField" in variableList[0] and isinstance(variableList[0]["isLeadField"], bool) and "value" in variableList[0] and isinstance(variableList[0]["value"], str)) else (False, None, "Set Variable component must have a non empty variable list",),
            #"variable": lambda variable: (True, variable, None,) if isinstance(variable, str) else (False, None, "No 'variable' in Set Variable component",),
            #"isLeadField": lambda isLeadField: (True, isLeadField, None,) if isinstance(isLeadField, bool) else (False, None, "isLeadField in Set Variable component must be True/False",),            
            #"value": lambda value: (True, value, None,) if isinstance(value, str) else (False, None, "Invalid 'value' in Set Variable component"),            
        }
        optional_constraints = {
            "variableType": lambda variableType: (True, variableType, None,) if isinstance(variableType, str) else (False, None, "Invalid 'variableType' in Set Variable component",), 
            #"variableExpression": lambda variableExpression: (True, variableExpression, None,) if isinstance(variableExpression, str) else (False, None, "Invalid 'variableExpression' in Set Variable component",), 
        }

        validated_data = self.validate(node, key, required_constaints=required_constaints, optional_constraints=optional_constraints, toggles={})
        
        self.node_dict[key] = validated_data

        # ----------------------------- #
        self.set_variable_dict(node, multiple=True, field='variableList')
        self.set_lead_dict(node, multiple=True, field='variableList') 
        # ----------------------------- #

        return node
    

    def parse_goal_component(self, node, key):
        required_constaints = {
            "variable": lambda variable: (True, variable, None,) if isinstance(variable, str) and variable not in ["",] else (False, None, f"'variable' must be a non empty string in {self.node_dict[key]['nodeType'].capitalize()} component",),
            "isLeadField": lambda isLeadField: (True, isLeadField, None,) if isinstance(isLeadField, bool) else (False, None, f"isLeadField in {self.node_dict[key]['nodeType'].capitalize()} component must be True/False",),            
        }
        optional_constraints = {
        }

        validated_data = self.validate(node, key, required_constaints=required_constaints, optional_constraints=optional_constraints, toggles={})
        
        self.node_dict[key] = validated_data

        # Set the value to True for GOAL Component
        self.node_dict[key]['value'] = 'true'

        self.set_variable_dict(node, "false")
        self.set_lead_dict(node) 

        return node


    def parse_set_variable_node_beta(self, node, key):
        required_constaints = {
            "variable": lambda variable: (True, variable, None,) if isinstance(variable, str) else (False, None, "No 'variable' in Set Variable component",),
            "isLeadField": lambda isLeadField: (True, isLeadField, None,) if isinstance(isLeadField, bool) else (False, None, "isLeadField in Set Variable component must be True/False",),            
            "value": lambda value: (True, value, None,) if isinstance(value, str) else (False, None, "Invalid 'value' in Set Variable component"),            
            "variableType": lambda variableType: (True, variableType, None,) if isinstance(variableType, str) else (False, None, "Invalid 'variableType' in Set Variable component",), 
            #"variableExpression": lambda variableExpression: (True, variableExpression, None,) if isinstance(variableExpression, str) else (False, None, "Invalid 'variableExpression' in Set Variable component",), 
            "routing": lambda routing: (True, routing, None,) if isinstance(routing, dict) and (('success' in routing) and ('error' in routing)) else (False, None, "'routing' component is invalid",),
        }
        optional_constraints = {
        }

        self.node_dict[key] = self.parse_multiple_choice_node(node, key, super_component='set_variable')
        
        validated_data = self.validate(node, key, required_constaints=required_constaints, optional_constraints=optional_constraints, toggles={})
        
        self.node_dict[key] = validated_data

        # ----------------------------- #
        # TODO: Remove this completely
        self.set_variable_dict(node)
        self.set_lead_dict(node) 
        # ----------------------------- #

        return node


    def assign_targetid(self, node, key):
        if len(self.source_target[key]) == 0:
            node['targetId'] = ""
        else:
            node['targetId'] = self.source_target[key][0]
        return node


    def parse_supercomponent(self, node, key, component=None, super_component=None, props={}):
        if super_component is None:
            return node
        
        if component == 'multiple_choice':
            required_props = ['buttons']
            for prop_name in required_props:
                if prop_name not in props:
                    raise BotJSONParseError(f"For Multi Choice Node, '{prop_name}' property is not present")

            buttons = props.get('buttons')
        
            if super_component == 'webhook':
                node['routing'] = {}
                for button in buttons:
                    if 'text' not in button or 'targetId' not in button:
                        raise BotJSONParseError(f"Routing Component for Webhook doesn't have buttons of the form {'text': '', 'targetId': ''}")

                    status_code = button['text'].lower()
                    target_id = button['targetId']
                    try:
                        status_code = int(status_code)
                    except:
                        if status_code not in ["default", "error"]:
                            raise BotJSONParseError(f"Routing component for Webhook cannot have routing code: {status_code}")
                    
                    if status_code in node['routing']:
                        raise BotJSONParseError(f"Routing component for Webhook has duplicate status codes for code: {status_code}")
                    
                    node['routing'][status_code] = target_id
                
                if 'default' not in node['routing']:
                    raise BotJSONParseError(f"Routing component for Webhook must have a 'default' option")

                if 'error' not in node['routing']:
                    # Set the error component as default itself
                    node['routing']['error'] = node['routing']['default']
            
            elif super_component == 'set_variable':
                node['routing'] = {}
                valid_statuses = ["success", "error"]

                for button in buttons:
                    if 'text' not in button or 'targetId' not in button:
                        raise BotJSONParseError(f"Routing Component for Set Variable doesn't have buttons of the form {'text': '', 'targetId': ''}")

                    status = button['text'].lower()
                    target_id = button['targetId']
                    if status not in valid_statuses:
                        raise BotJSONParseError(f"Routing component for Set Variable can have only statuses {valid_statuses}")
                    
                    if status in node['routing']:
                        raise BotJSONParseError(f"Routing component for Set Variable has duplicate status for: {status}")
                    
                    node['routing'][status] = target_id

                if 'error' not in node['routing']:
                    # Set the error component to stop
                    node['routing']['error'] = ""
        return node


    def set_webhook_timeout(self, timeout):
        if timeout is None:
            return WEBHOOK_TIMEOUT
        else:
            try:
                _timeout = float(timeout)
                if _timeout > WEBHOOK_TIMEOUT or _timeout <= 0:
                    raise BotJSONParseError
                return _timeout
            except:
                return None
    

    def _dfs(self, init_id):
        self.stack = [(init_id, dict(),)]

        while self.stack != []:
            node_id, symbol_table = self.stack.pop()
            symbol_table = deepcopy(symbol_table)
            if node_id not in self.visited_nodes:
                self.visited_nodes.add(node_id)
            else:
                continue
            
            # Check if a variable is coming before it has been initialized
            list_components = ['choices', 'messages']
            for component in list_components:
                if component in self.node_dict[node_id]:
                    msgs = self.node_dict[node_id][component]
                    for msg in msgs:
                        variable_tokens = self.message_to_variable_tokenizer(msg)
                        for variable_token in variable_tokens:
                            if variable_token not in symbol_table:
                                raise BotJSONParseError(f"Variable {variable_token} inside component {self.node_dict[node_id]['nodeType'].capitalize()} is not previously set")
                        
            '''
            webhook_component = ['queryParams', 'requestBody', 'responseBody']
            for component in webhook_component:
                if component in self.node_dict[node_id]:
                    content = self.node_dict[node_id][component]
                    for _, variable_token in content.items():
                        if variable_token not in symbol_table:
                            raise BotJSONParseError(f"Variable {variable_token} inside component {self.node_dict[node_id]['nodeType'].capitalize()} is not previously set")
            '''
            
            if 'variable' in self.node_dict[node_id]:
                variable = self.node_dict[node_id]['variable']

                if 'variableType' in self.node_dict[node_id]:
                    variable_type = self.node_dict[node_id]['variableType']
                    if variable not in symbol_table or 'type' not in symbol_table[variable]:
                        symbol_table[variable] = {'type': variable_type}
                    elif symbol_table[variable]['type'] is not None and variable_type != symbol_table[variable]['type']:
                        raise BotJSONParseError(f"Variable {variable} inside component {self.node_dict[node_id]['nodeType'].capitalize()} must be of type {variable_type}, but has {symbol_table[variable]['type']}")
                else:
                    if variable in symbol_table:
                        symbol_table[variable]['type'] = None
                    else:
                        symbol_table[variable] = {'type': 'string'}
                
                if self.node_dict[node_id]['nodeType'] == 'SET_VARIABLE_BETA':
                    if 'value' in self.node_dict[node_id] and self.node_dict[node_id]['value'] is not None:
                        variable_expression = self.node_dict[node_id]['value']

                        try:    
                            self.node_dict[node_id]['tokens'] = self.tokenize_expression(variable_expression)
                        except BotJSONParseError as ex:
                            raise BotJSONParseError(f"Inside component {self.node_dict[node_id]['nodeType'].capitalize()}, {ex}")
                        
                        tokens = self.node_dict[node_id]['tokens']
                        
                        for i in range(len(tokens)):
                            if tokens[i]['type'] == 'EQUALS':
                                raise BotJSONParseError(f"Set Variable expression must not have '='")
                        
                        try:
                            self.parse_expression(self.node_dict[node_id]['tokens'], symbol_table, expression_type=self.node_dict[node_id].get('variableType', 'string'))
                        except BotJSONParseError as  ex:
                            raise BotJSONParseError(f"Inside component {self.node_dict[node_id]['nodeType'].capitalize()}, {ex}")
            
            if 'buttons' in self.node_dict[node_id] and isinstance(self.node_dict[node_id]['buttons'], list):
                for button in self.node_dict[node_id]['buttons']:
                    if 'text' in button:
                        msg = button['text']
                        variable_tokens = self.message_to_variable_tokenizer(msg)
                        for variable_token in variable_tokens:
                            if variable_token not in symbol_table:
                                raise BotJSONParseError(f"Variable {variable_token} inside component {self.node_dict[node_id]['nodeType'].capitalize()} is not previously set")
                    
                    if 'targetId' in button:
                        target_id = button['targetId']
                        self.stack.append((target_id, symbol_table,))

            elif 'targetId' in self.node_dict[node_id] and self.node_dict[node_id]['targetId'] != "":
                target_id = self.node_dict[node_id]['targetId']
                self.stack.append((target_id, symbol_table,))
            
            else:
                continue
    

    def semantic_analysis(self):   
        # Start from INIT Component
        if self.init_component_id is None:
            raise BotJSONParseError(f"INIT Component ID is invalid")
        self._dfs(self.init_component_id)
    

    def tokenize_expression(self, expression):
        tokens = []
        lexer_rules = [
            (r'[0-9]{1,2}\:[0-5][0-9]\:[0-5][0-9]', 'TIME'),
            (r'[0-9]{2}-[0-9]{2}-[0-9]{4}', 'DATE'),
            (r'[\'\"][a-zA-Z0-9_\s\(\)]*[\'\"]', 'STRING'),
            (r'\d+\.\d+', 'FLOAT'),
            (r'\d+', 'NUMBER'),
            (r'\@[a-zA-Z_]\w*', 'IDENTIFIER'),
            (r'True', 'TRUE'),
            (r'False', 'FALSE'),
            (r'and', 'AND'),
            (r'or', 'OR'),
            (r'not', 'NOT'),
            (r'\+', 'PLUS'),
            (r'\-', 'MINUS'),
            (r'\*', 'MUL'),
            (r'\/', 'DIV'),
            (r'\(', 'LP'),
            (r'\)', 'RP'),
            (r'\{', 'LBP'),
            (r'\}', 'RBP'),
            (r'\%', 'MOD'),
            (r'==', 'ISEQUAL'),
            (r'=', 'EQUALS'),
            (r'\?', 'TERNARY'),
        ]

        lex = Lexer(lexer_rules, skip_whitespace=True)
        lex.input(expression)

        try:
            tokens = [{'type': token.type, 'value': token.val} for token in lex.tokens()]
        except LexerError:
            raise BotJSONParseError(f"Invalid expression")

        return tokens
    

    def parse_expression(self, tokens, symbol_table, expression_type='string'):
        for token in tokens:
            if token['type'] == 'IDENTIFIER':
                if token['value'].startswith("@") == False:
                    raise BotJSONParseError(f"Invalid Expression")
                if token['value'] not in symbol_table:
                    raise BotJSONParseError(f"Variable {token['value']} not set previously")
                if 'type' in symbol_table[token['value']]:
                    symbol_type = symbol_table[token['value']]['type']
                    if symbol_type != expression_type:
                        raise BotJSONParseError(f"Cannot assign type {symbol_type} to variable {token['value']} of type {expression_type}")
            else:
                symbol_type = self.type_expression_dict.get(token['type'])
                if symbol_type in self.required_variable_types and symbol_type != expression_type:
                    raise BotJSONParseError(f"Cannot assign type {symbol_type} to variable of type {expression_type}")
        
        #expression_string = ''.join([token['value'] if ((token['value'].startswith("@") == False) or (token['type'] != "IDENTIFIER")) else token['value'].replace("@", self.clientwidget_keyspace) for token in tokens])
        #return expression_string
