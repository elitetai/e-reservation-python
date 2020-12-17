import os
import json
from dotenv import load_dotenv
from pymongo import ReturnDocument
from bson import ObjectId, json_util
from flask import Flask, jsonify, request
from flask_pymongo import PyMongo
from flask_cors import CORS

app = Flask(__name__)
load_dotenv()

app.config["MONGO_URI"]=os.getenv("MONGO_URI")
mongo = PyMongo(app)

cors = CORS(app, resources={r"/*": {"origins": "*"}})
inputs = mongo.db.inputs

def parse_json(data):
    return json.loads(json_util.dumps(data))

# get current table setting
def current_setting():
    get_data = inputs.find_one(
        {'tables': {'$exists':True}, 
        'chairsPerTable': {'$exists':True}})
    return get_data

# owner gets tables + chairs per table
@app.route('/owner', methods=['GET'])
def get_tables_data():
    tables = current_setting()['tables']
    settings = [current_setting(), {'table_count':table_count(tables)}]  
    return jsonify(parse_json(settings))

# owner sets tables  + chairs per table
@app.route('/update_setting', methods=['POST'])
def update_setting():
    get_id = request.json['id']
    tables = int(request.json['tables'])
    chairsPerTable = int(request.json['chairsPerTable'])
    if tables <= 0 or chairsPerTable <= 0:
        response = jsonify({
            'msg': 'Tables or chairs per table must be at least one!',
            'status': 'Failed'
        }), 400
    else: 
        settings = inputs.find_one_and_update(
            {'_id': ObjectId(get_id)},
            {'$set': {'tables': tables, 
            'chairsPerTable': chairsPerTable}},
            return_document=ReturnDocument.AFTER)
        # recalculate & populate table counts
        update_table_count = inputs.find_one_and_update(
            {'table_count':{'$exists':True}},
            {'$set': {'table_count': table_count(tables)}},
            return_document=ReturnDocument.AFTER)
        response = jsonify(parse_json(settings)), 201
    return response

# original table count
def table_count(tables):
    table_list = [f'T{table+1}' for table in range(0, tables)]
    return table_list

# gets current available table count 
def updated_table_count():
    table_count = inputs.find_one({'table_count':{'$exists':True}})
    return table_count['table_count']

# for API purposes
@app.route('/current_table_count',methods=['GET'])
def current_table_count():
    return jsonify(updated_table_count())

def table_allocate(tables_required):
    table_list = updated_table_count()
    if len(table_list) >= tables_required:
        waiting = 0
        allocated = [table_list.pop(0) for i in range(0,tables_required)]
        update_table_count = inputs.update_one(
            {'table_count': {'$exists':True}},
            {'$set': {'table_count': table_list}})
    else:
        waiting = tables_required - len(table_list)
        allocated = [table_list.pop(0) for i in range(0,len(table_list))]
        update_table_count = inputs.update_one(
            {'table_count': {'$exists':True}},
            {'$set': {'table_count': table_list}})
    return allocated, waiting

# delete allocated tables
@app.route('/table_unallocate', methods=['POST'])
def table_unallocate():
    table_name = request.json['table_name']
    table_list = updated_table_count()
    table_list.insert(len(table_list), table_name)
    update_table_count = inputs.update_one(
        {'table_count': {'$exists':True}},
        {'$set': {'table_count': table_list}})
    return jsonify(parse_json(table_list))

# gets all the queue no
def show_queue():
    queue_list = inputs.find_one({'queue_list':{'$exists': True}})
    return queue_list['queue_list']

# API purpose
@app.route('/get_queue', methods=['GET'])
def get_queue():
    return jsonify(show_queue())

# Allocate queue no to respective table name
@app.route('/allocate_queue', methods=['POST'])
def allocate_queue():
    queue_no = int(request.json['queue_no'])
    table_name = request.json['table_name']
    table_list = updated_table_count()
    if queue_no in show_queue():
        for table in table_name:
            table_list.remove(table)
            update_table_count = inputs.update_one(
                {'table_count': {'$exists':True}},
                {'$set': {'table_count': table_list}})
        delete_queue = inputs.find_one_and_update(
            {'queue_list':{'$exists': True}},
            {'$pull':{'queue_list':queue_no}},
            return_document=ReturnDocument.AFTER)
        output = [delete_queue, {'table_count':table_list}] 
        response = jsonify(parse_json(output))
    else:
        response = jsonify({
            'msg': f'Queue number {queue_no} not found',
            'status': 'Failed'
        }), 404
    return response

# customer submission on headcount and obtain response on reservation
@app.route('/update_headcount', methods=['POST'])
def update_headcount():
    headcount = int(request.json['headcount'])
    tables = int(current_setting()['tables'])
    chairsPerTable = int(current_setting()['chairsPerTable'])

    if headcount <= 0:
        response = jsonify({
            'msg': 'Headcount must be at least one person!',
            'status': 'Failed'           
        }), 400
        return response

    import math
    tables_required = math.ceil(headcount/chairsPerTable)
    table_allocation = table_allocate(tables_required) 
    table_waiting_count = table_allocation[1]
    table_names = table_allocation[0]
    if table_waiting_count:     
        remaining_headcount = headcount - (len(table_names)*chairsPerTable)
    else:
        remaining_headcount = 0

    # how many customers are required to wait with queue no (inc it)
    if remaining_headcount: 
        queue_no = inputs.find_one_and_update(
            {'queue_no': {'$exists':True}},
            {'$inc':{'queue_no':1}},
            return_document=ReturnDocument.AFTER)
        add_queue = inputs.find_one_and_update(
            {'queue_list': {'$exists':True}}, 
            {'$push':{'queue_list':queue_no['queue_no']}})
        queue_no = parse_json(queue_no['queue_no'])
    else: 
        queue_no = 0

    allocated_headcount = headcount-remaining_headcount
    allocated_remainder = allocated_headcount % chairsPerTable
    allocated_calculation = allocated_headcount
    table_headcount_pair = []
    for name in table_names:
        if allocated_remainder == 0:
            table_headcount_pair.append({
                'name':name,
                'count':chairsPerTable
                })
        else: 
            if chairsPerTable >= allocated_calculation:
                table_headcount_pair.append({
                    'name':name,
                    'count':allocated_calculation
                    }) 
                allocated_calculation -= chairsPerTable
            else:
                table_headcount_pair.append({
                    'name':name,
                    'count':chairsPerTable
                    })
                allocated_calculation -= chairsPerTable
                
    response = jsonify([{
        'headcount': headcount,
        'tables_required': tables_required, 
        'table_headcount_pair': table_headcount_pair, 
        'remaining_headcount': remaining_headcount,
        "queue_no": queue_no,
        }])

    ## (KIV) not saving any customer info at the moment
    # customer = inputs.insert_one({
    #     'headcount': headcount,
    #     'tables_required': tables_required, 
    #     'table_headcount_pair': table_headcount_pair, 
    #     'remaining_headcount': remaining_headcount,
    #     "queue_no": queue_no,
    #     })

    return response

if __name__ == '__main__':
    app.run()