import jenkins
import sys
import logging
import time
from xml.sax.saxutils import escape


# Set up logging
logging.basicConfig(level=logging.INFO)


def delete_job_if_exists(server, job_name):
    """
    Delete a Jenkins job if it exists.
    """
    try:
        if server.job_exists(job_name):
            logging.info(f"Job {job_name} exists. Attempting to delete.")
            server.delete_job(job_name)
            logging.info(f"Job {job_name} deleted.")
        else:
            logging.info(f"Job {job_name} does not exist. No need to delete.")
    except Exception as e:
        logging.error(f"Error deleting job {job_name}: {e}")


def create_job(server, job_name, jenkinsfile_content):
    """
    Create a Jenkins job with the provided Jenkinsfile content.
    """
    pipeline_xml = f"""
    <flow-definition plugin="workflow-job@2.40">
        <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps@2.90">
            <script>{escape(jenkinsfile_content)}</script>
            <sandbox>true</sandbox>
        </definition>
        <!-- Other configurations as needed -->
    </flow-definition>
    """

    try:
        logging.info(f"Creating new job {job_name}.")
        server.create_job(job_name, pipeline_xml)
        logging.info(f"Job {job_name} created successfully.")
    except Exception as e:
        logging.error(f"Error creating job {job_name}: {e}")


def start_jenkins_job_and_stream_output(server, job_name):
    """
    Start a Jenkins job and stream its output.
    """
    try:
        queue_number = server.build_job(job_name)
        logging.info(f"Job {job_name} build started. Queue number: {queue_number}")
        build_number = None
        while True:
            queue_info = server.get_queue_item(queue_number)
            if "executable" in queue_info and queue_info["executable"] is not None:
                build_number = queue_info["executable"]["number"]
                logging.info(
                    f"Job {job_name} is building. Build number: {build_number}"
                )
                break
            else:
                logging.info("Waiting for job to start...")
                time.sleep(2)

        if build_number:
            stream_job_output(server, job_name, build_number)
    except Exception as e:
        logging.error(f"Error starting job {job_name}: {e}")


def stream_job_output(server, job_name, build_number):
    """
    Stream the console output of a Jenkins job.
    """
    try:
        offset = 0
        while True:
            build_info = server.get_build_info(job_name, build_number)
            if build_info["building"]:
                full_output = server.get_build_console_output(job_name, build_number)
                new_output = full_output[offset:]
                print(new_output, end="")
                offset += len(new_output)
                time.sleep(2)
            else:
                break
        full_output = server.get_build_console_output(job_name, build_number)
        new_output = full_output[offset:]
        print(new_output, end="")
    except Exception as e:
        logging.error(f"Error streaming output for job {job_name}: {e}")


def main():
    jenkins_user = "admin"
    jenkins_dict = {
        "kitchen": {
            "url": "",
            "token": "",
        },
        "oven": {
            "url": "",
            "token": "",
        },
        "grill": {
            "url": "https://grill-based-journey.ngrok.app",
            "token": "115a39e964c5a34df6845b0da76cb2c594",
        },
        "microwave": {
            "url": "",
            "token": "",
        },
    }
    job_name = sys.argv[1]
    master_select = sys.argv[2]

    jenkins_details = jenkins_dict[master_select]
    server = jenkins.Jenkins(
        jenkins_details["url"],
        username=jenkins_user,
        password=jenkins_details["token"],
    )

    delete_job_if_exists(server, job_name)

    # Read Jenkinsfile content
    jenkinsfile_path = f"raw/{job_name}.Jenkinsfile"
    with open(jenkinsfile_path, "r") as file:
        jenkinsfile_content = file.read()

    create_job(server, job_name, jenkinsfile_content)
    start_jenkins_job_and_stream_output(server, job_name)


if __name__ == "__main__":
    main()
