import pandas as pd
from PerformanceRecorder import PerformanceRecorder
from neo4j import GraphDatabase


class ClusterConstructor:

    def __init__(self, password, name_data_set, entity_labels, action_lifecycle_label):
        self.driver = GraphDatabase.driver(
            "bolt://localhost:7687", auth=("neo4j", password))
        self.name_data_set = name_data_set
        self.entity_labels = entity_labels
        self.entity_labels[0].append('rID')
        self.entity_labels[1].append('cID')
        self.action_lifecycle_label = action_lifecycle_label

    def construct_clusters(self, df_patterns_clustered, nr_clusters):
        # create performance recorder
        pr = PerformanceRecorder(self.name_data_set, 'constructing_clusters')
        # check if the transactional lifecycle is recorded
        for index, row in df_patterns_clustered.iterrows():
            # write cluster as property to task instance nodes
            if not pd.isna(row['cluster']):
                query_write_clusters_to_task_instances = f'''
                                MATCH (ti:TaskInstance) WHERE ti.ID = {row['ID']}
                                SET ti.cluster = {row['cluster']}'''
                run_query(self.driver, query_write_clusters_to_task_instances)

        # create cluster nodes
        query_create_cluster_nodes = f'''
                MATCH (ti:TaskInstance) WHERE ti.cluster IS NOT NULL 
                WITH DISTINCT ti.cluster AS cluster, count(*) AS cluster_count
                MERGE (tc:TaskCluster {{Name:cluster, count:cluster_count}})'''
        run_query(self.driver, query_create_cluster_nodes)
        pr.record_performance('create_cluster_nodes')

        # link task instance nodes to corresponding cluster nodes
        query_link_task_instances_to_clusters = f'''
                MATCH (tc:TaskCluster)
                MATCH (ti:TaskInstance) WHERE ti.cluster = tc.Name
                CREATE (ti)-[:OBSERVED]->(tc)'''
        run_query(self.driver, query_link_task_instances_to_clusters)
        pr.record_performance('link_task_instances_to_cluster_nodes')

        for entity in self.entity_labels:
            # aggregate DF-relationships between clusters
            query_aggregate_directly_follows_clusters = f'''
                MATCH (tc1:TaskCluster)<-[:OBSERVED]-(ti1:TaskInstance)-[df:DF_TI]->(ti2:TaskInstance)-[:OBSERVED]->(tc2:TaskCluster)
                MATCH (ti1)-[:CORR]->(n)<-[:CORR]-(ti2)
                WHERE n.EntityType = "{entity[0]}" AND df.EntityType = "{entity[1]}"
                WITH n.EntityType as EType, tc1, count(df) AS df_freq, tc2
                MERGE (tc1)-[rel2:DF_TC{{EntityType:EType}}]->(tc2) ON CREATE SET rel2.count=df_freq'''
            run_query(self.driver, query_aggregate_directly_follows_clusters)
        pr.record_performance('aggregate_DF_relationships_between_clusters')

        # create artificial start and end nodes
        query_create_artificial_start_and_end = f'''
            CREATE (:TaskCluster {{Name:"start"}})
            CREATE (:TaskCluster {{Name:"end"}})
            '''
        run_query(self.driver, query_create_artificial_start_and_end)
        pr.record_performance('create_artificial_start_and_end_nodes')

        # connect artificial start and end for case perspective
        query_connect_artificial_start_case = f'''
            MATCH (tc:TaskCluster) WHERE NOT (:TaskCluster)-[:DF_TC {{EntityType:"case"}}]->(tc)  
                AND NOT tc.Name IN ["start", "end"]
            WITH tc, tc.count AS count
            MATCH (start:TaskCluster {{Name:"start"}})
            WITH start, tc, count
            MERGE (start)-[df:DF_TC {{EntityType:"case", count:count}}]->(tc)
            '''
        run_query(self.driver, query_connect_artificial_start_case)
        query_connect_artificial_end_case = f'''
            MATCH (tc:TaskCluster) WHERE NOT (tc)-[:DF_TC {{EntityType:"case"}}]->(:TaskCluster) 
                AND NOT tc.Name IN ["start", "end"]
            WITH tc, tc.count AS count
            MATCH (end:TaskCluster {{Name:"end"}})
            WITH end, tc, count
            MERGE (tc)-[df:DF_TC {{EntityType:"case", count:count}}]->(end)
            '''
        run_query(self.driver, query_connect_artificial_end_case)
        pr.record_performance(
            'connect_artificial_start_and_end_for_case_perspective')

        # connect artificial start and end for resource perspective
        query_connect_artificial_start_resource = f'''
            MATCH (ti0:TaskInstance)-[df:DF_TI {{EntityType:"resource"}}]->(ti1:TaskInstance) 
                WHERE NOT date(ti0.end_time) = date(ti1.start_time) AND ti1.cluster IS NOT NULL
            WITH DISTINCT ti1.cluster AS cluster, count(*) AS count
            MATCH (tc:TaskCluster {{Name:cluster}})
            WITH tc, count
            MATCH (start:TaskCluster {{Name:"start"}})
            WITH tc, start, count
            MERGE (start)-[df:DF_TC {{EntityType:"resource", count:count}}]->(tc)
            '''
        run_query(self.driver, query_connect_artificial_start_resource)
        query_connect_artificial_end_resource = f'''
            MATCH (ti0:TaskInstance)-[df:DF_TI {{EntityType:"resource"}}]->(ti1:TaskInstance) WHERE NOT date(ti0.end_time) = date(ti1.start_time) AND ti0.cluster IS NOT NULL
            WITH DISTINCT ti0.cluster AS cluster, count(*) AS count
            MATCH (tc:TaskCluster {{Name:cluster}})
            WITH tc, count
            MATCH (end:TaskCluster {{Name:"end"}})
            WITH tc, end, count
            MERGE (tc)-[df:DF_TC {{EntityType:"resource", count:count}}]->(end)
                        '''
        run_query(self.driver, query_connect_artificial_end_resource)
        pr.record_performance(
            'connect_artificial_start_and_end_for_resource_perspective')

        pr.record_total_performance()
        pr.save_to_file()


def run_query(driver, query):
    with driver.session() as session:
        result = session.run(query).single()
        if result:
            return result.value()
        else:
            return None
