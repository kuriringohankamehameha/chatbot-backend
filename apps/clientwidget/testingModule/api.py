import json
import os
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

RELATIVE_PATH = 'apps/clientwidget_updated/testingModule/'

def MergeDict(dict1, dict2):
    return {**dict1, **dict2}

class TestingWebhookCompoenent(APIView):

    def get(self, request):

        data = dict()
        with open(os.path.join(RELATIVE_PATH, 'dummy.json')) as json_file:
            data = json.load(json_file)
        data['parameters'] = self.request.query_params
        data['headers'] = self.request.headers

        if 'status' in self.request.query_params:
            code = int(self.request.query_params['status'])
            return Response(data, status=code)
        else:
            return Response(data)

    def post(self, request):

        data = self.request.data

        with open(os.path.join(RELATIVE_PATH, 'dummy.json'), 'w') as json_file:
            json.dump(data, json_file)
        
        response = dict()
        response['parameters'] = self.request.query_params
        response['headers'] = self.request.headers
        response['status'] = 'Data posted successfully'

        if 'status' in self.request.query_params:
            code = int(self.request.query_params['status'])
            return Response(response, status=code)
        else:
            return Response(response)

    def put(self, request):

        data = self.request.data

        with open(os.path.join(RELATIVE_PATH, 'dummy.json'), 'w+') as json_file:
            prev_data = json.load(json_file)
            final_data = json.loads(MergeDict(prev_data, data))
            print(final_data)
            json_file.write(final_data)

        response = dict()
        response['parameters'] = self.request.query_params
        response['headers'] = self.request.headers
        response['status'] = 'Data posted successfully'

        if 'status' in self.request.query_params:
            code = int(self.request.query_params['status'])
            return Response(response, status=code)
        else:
            return Response(response)
    
    def delete(self, request):

        replace_value = dict()
        with open(os.path.join(RELATIVE_PATH, 'dummy.json'), 'w') as json_file:
            json.dump(replace_value, json_file)
        
        response = dict()
        response['parameters'] = self.request.query_params
        response['headers'] = self.request.headers
        response['status'] = 'Data deleted successfully'

        if 'status' in self.request.query_params:
            code = int(self.request.query_params['status'])
            return Response(response, status=code)
        else:
            return Response(response)

            