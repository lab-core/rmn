def convert_box_to_list(position_dict):
    # Check if all the keys are in the dictionary
    if position_dict is None or not position_dict.keys() & {"x1", "x2", "y1", "y2"}:
        return None
    if position_dict['x1'] == None or position_dict['x2'] == None or position_dict['y1'] == None or position_dict['y2'] == None :
        return None

    return [position_dict['x1']/100.0, position_dict['x2']/100.0, position_dict['y1']/100.0, position_dict['y2']/100.0]
    
def convert_box_to_dict(position_list):
    if position_list == None or len(position_list) != 4: 
        return None
    
    return {
        'x1': position_list[0]*100.0,
        'x2': position_list[1]*100.0,
        'y1': position_list[2]*100.0,
        'y2': position_list[3]*100.0
    }  
