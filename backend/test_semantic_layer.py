import sys
import logging
sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO)

from semantic.ontology import SemanticBuilder

# Mock Schema Profile (what pandas would output)
mock_schema = {
    "Transaction_ID": "object",
    "Customer_Name": "object",
    "Store_Region": "object",
    "Product_Category": "object",
    "Purchase_Date": "datetime64[ns]",
    "Quantity": "int64",
    "Price": "float64",
    "Revenue": "float64",
    "Discount": "float64",
    "Cost": "float64"
}

# Mock Sample
mock_sample = {
    "Transaction_ID": ["T-1001", "T-1002"],
    "Customer_Name": ["John Doe", "Jane Smith"],
    "Store_Region": ["North", "South"],
    "Product_Category": ["Electronics", "Clothing"],
    "Purchase_Date": ["2023-01-01", "2023-01-02"],
    "Quantity": [1, 2],
    "Price": [199.99, 49.99],
    "Revenue": [199.99, 99.98],
    "Discount": [0.0, 10.0],
    "Cost": [150.0, 40.0]
}

def run_test():
    print("Building ontology...")
    builder = SemanticBuilder()
    ontology = builder.build("Test_Sales_Dataset", mock_schema, mock_sample)
    
    print("\n" + "="*50)
    print(f"Dataset Domain: {ontology.domain}")
    print("="*50)
    
    print("\nClassifications:")
    for col_name, col in ontology.columns.items():
        primary = "* (Primary)" if col.is_primary_metric or col.is_primary_date else ""
        concept = f"[{col.concept}]" if col.concept else ""
        print(f"  - {col_name.ljust(20)} : {col.role.ljust(15)} {concept.ljust(25)} {primary}")
        
    print("\nDerived Metrics Suggested:")
    for metric in ontology.derived_metrics:
        print(f"  - {metric['name']}: {metric['formula']}")
        
if __name__ == "__main__":
    run_test()
