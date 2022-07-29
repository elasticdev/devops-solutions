class Main(newSchedStack):

    def __init__(self,stackargs):

        newSchedStack.__init__(self,stackargs)

        # Add default variables
        self.parse.add_required(key="codebuild_name")
        self.parse.add_required(key="git_repo")
        self.parse.add_required(key="git_url")
        self.parse.add_required(key="project_id",default="null")

        self.parse.add_optional(key="slack_channel",default="null")
        self.parse.add_optional(key="ecr_repository_uri",default="null")
        self.parse.add_optional(key="ecr_repo_name",default="null")
        self.parse.add_optional(key="docker_repository_uri",default="null")
        self.parse.add_optional(key="docker_repo_name",default="null")
        self.parse.add_optional(key="docker_username",default="null")
        self.parse.add_optional(key="run_title",default="codebuild_ci")
        self.parse.add_optional(key="trigger_id",default="_random")
        self.parse.add_optional(key="privileged_mode",default="true")
        self.parse.add_optional(key="image_type",default="LINUX_CONTAINER")
        self.parse.add_optional(key="build_image",default="aws/codebuild/standard:5.0")
        self.parse.add_optional(key="build_timeout",default="444")
        self.parse.add_optional(key="compute_type",default="BUILD_GENERAL1_SMALL")
        self.parse.add_optional(key="secret",default="_random")
        self.parse.add_optional(key="branch",default="master")

        self.parse.add_required(key="ci_environment")
        self.parse.add_optional(key="suffix_id",default="null")  # this is required to make the buckets unique
        self.parse.add_optional(key="suffix_length",default="4")  

        self.parse.add_optional(key="docker_registry",default="ecr")
        self.parse.add_optional(key="aws_default_region",default="us-west-1")
        self.parse.add_optional(key="cloud_tags_hash",default="null")
        self.parse.add_optional(key="bucket_acl",default="private")
        self.parse.add_optional(key="bucket_expire_days",default="1")

        # Add substack
        self.stack.add_substack('elasticdev:::aws_s3_bucket')
        self.stack.add_substack('elasticdev:::new_github_ssh_key')
        self.stack.add_substack('elasticdev:::aws_dynamodb_item','dynamodb')
        self.stack.add_substack('elasticdev:::aws_ssm_param')
        self.stack.add_substack('elasticdev:::aws_codebuild')
        self.stack.add_substack('elasticdev:::github_webhook')

        self.stack.init_substacks()

    def _determine_suffix_id(self):

        if self.stack.suffix_id: return self.stack.suffix_id.lower()

        return self.stack.b64_encode(self.stack.ci_environment)[0:int(self.stack.suffix_length)].lower()

    def _get_api_url(self):

        import os

        apigateway_name = "ed-codebuild-shared-{}".format(self.stack.ci_environment)

        _lookup = {"must_be_one":True}
        _lookup["resource_type"] = "apigateway_restapi_lambda"
        _lookup["provider"] = "aws"
        _lookup["name"] = apigateway_name

        results = self.stack.get_resource(**_lookup)[0]

        return os.path.join(str(results["base_url"]),str(self.stack.trigger_id))

    def _get_ssh_private_key(self):

        key_name = "{}-codebuild-deploy-key".format(self.stack.codebuild_name)

        _lookup = {"must_be_one":True}
        _lookup["resource_type"] = "ssh_key_pair"
        _lookup["provider"] = "ed"
        _lookup["name"] = key_name

        results = self.stack.get_resource(decrypt=True,**_lookup)[0]

        return self.stack.b64_encode(results["private_key"])

    def _get_ecr_uri(self):

        if not self.stack.ecr_repo_name: return

        docker_repo = self.stack.check_resource(name=self.stack.ecr_repo_name,
                                                resource_type="ecr_repo",
                                                provider="aws",
                                                must_exists=True)[0]

        return docker_repo["repository_uri"]

    def _set_codebuild_buckets(self):

        suffix_id = self._determine_suffix_id()

        self.s3_bucket_cache = "{}-codebuild-{}-cache".format(self.stack.codebuild_name,
                                                              suffix_id)

        self.s3_bucket_output = "{}-codebuild-{}-output".format(self.stack.codebuild_name,
                                                                suffix_id)

    def _webhook(self):

        self.stack.init_variables()

        _name = "ed-codebuild-{}-{}".format(self.stack.ci_environment,self.stack.codebuild_name)
        _url = self._get_api_url()

        default_values = { "aws_default_region":self.stack.aws_default_region,
                           "repo":self.stack.git_repo,
                           "secret":self.stack.secret }

        overide_values = { "name": _name,
                           "url": _url }

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "continuous_delivery"
        inputargs["human_description"] = 'Create Github webhook for codebuild "{}"'.format(self.stack.codebuild_name)
    
        return self.stack.github_webhook.insert(display=True,**inputargs)

    def run_setup(self):

        self.stack.init_variables()
        self.stack.set_parallel()

        self._sshdeploy()
        self._token()
        self.stack.unset_parallel()

        self._s3()
        self._dynamodb()

        return self._webhook()

    def _s3(self):

        default_values = { "aws_default_region":self.stack.aws_default_region }

        if "_" in self.stack.codebuild_name:
            msg = "Cannot use underscores (Only hyphens) in the codebuild_name"
            raise Exception(msg)

        self._set_codebuild_buckets()

        overide_values = { "bucket": self.s3_bucket_cache,
                           "acl": self.stack.bucket_acl,
                           "expire_days": self.stack.bucket_expire_days,
                           "force_destroy": "true",
                           "enable_lifecycle": "true" }

        if self.stack.cloud_tags_hash: overide_values["cloud_tags_hash"] = self.stack.cloud_tags_hash

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "continuous_delivery"
        inputargs["human_description"] = 'Create s3 bucket "{}" cache'.format(self.s3_bucket_cache)
    
        self.stack.aws_s3_bucket.insert(display=True,**inputargs)

        overide_values = { "bucket": self.s3_bucket_output,
                           "acl": self.stack.bucket_acl,
                           "expire_days": self.stack.bucket_expire_days,
                           "force_destroy": "true",
                           "enable_lifecycle": "true" }

        if self.stack.cloud_tags_hash: overide_values["cloud_tags_hash"] = self.stack.cloud_tags_hash

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "continuous_delivery"
        inputargs["human_description"] = 'Create s3 bucket "{}" output'.format(self.s3_bucket_output)
    
        return self.stack.aws_s3_bucket.insert(display=True,**inputargs)

    def _sshdeploy(self):

        key_name = "{}-codebuild-deploy-key".format(self.stack.codebuild_name)

        default_values = { "aws_default_region":self.stack.aws_default_region,
                           "repo":self.stack.git_repo }

        overide_values = { "key_name": key_name }

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "continuous_delivery"
        inputargs["human_description"] = 'Create deploy key "{}"'.format(key_name)
    
        return self.stack.new_github_ssh_key.insert(display=True,**inputargs)

    def run_ssm(self):

        self.stack.init_variables()
        self._set_ssm_keys()

        # add ed token
        default_values = { "aws_default_region":self.stack.aws_default_region }

        overide_values = { "ssm_key": self.stack.ssm_callback_token,
                           "ssm_value": self._get_token() }

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "continuous_delivery"
        inputargs["human_description"] = 'ED callback token to ssm'
    
        self.stack.aws_ssm_param.insert(display=True,**inputargs)

        # add ssh key
        default_values = { "aws_default_region":self.stack.aws_default_region }

        overide_values = { "ssm_key": self.stack.ssm_ssh_key,
                           "ssm_value": self._get_ssh_private_key() }

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "continuous_delivery"
        inputargs["human_description"] = 'Upload private ssh key to ssm'

        self.stack.aws_ssm_param.insert(display=True,**inputargs)

        # add docker token
        docker_token = self.stack.inputvars.get("docker_token")

        if not docker_token: 
            docker_token = self.stack.inputvars.get("DOCKER_TOKEN")

        if not docker_token: 
            docker_token = self.stack.inputvars.get("DOCKERHUB_TOKEN")

        self.stack.logger.debug(self.stack.inputvars)
        raise Exception(self.stack.inputvars)

        if docker_token:

            default_values = { "aws_default_region":self.stack.aws_default_region }

            overide_values = { "ssm_key": self.stack.ssm_docker_token,
                               "ssm_value": docker_token }

            inputargs = { "default_values":default_values,
                          "overide_values":overide_values }
    
            inputargs["automation_phase"] = "continuous_delivery"
            inputargs["human_description"] = 'Upload docker token to ssm'
    
            self.stack.aws_ssm_param.insert(display=True,**inputargs)

        # add slack_webhook_hash
        slack_webhook_hash = self.stack.inputvars.get("slack_webhook_hash")

        if slack_webhook_hash:

            default_values = { "aws_default_region":self.stack.aws_default_region }

            overide_values = { "ssm_key": self.stack.ssm_slack_webhook_hash,
                               "ssm_value": slack_webhook_hash }

            inputargs = { "default_values":default_values,
                          "overide_values":overide_values }
    
            inputargs["automation_phase"] = "continuous_delivery"
            inputargs["human_description"] = 'Upload slack webhook url to ssm'
    
            self.stack.aws_ssm_param.insert(display=True,**inputargs)

        return True

    def _get_s3_bucket(self):

        suffix_id = self._determine_suffix_id()
        return "codebuild-shared-{}-{}".format(self.stack.ci_environment,suffix_id)

    def _set_docker_items(self,item):

        if self.stack.ssm_docker_token: 
            item["ssm_docker_token"] = { "S":str(self.stack.ssm_docker_token) }

        # determine docker repository uri
        if self.stack.docker_username:
            item["docker_username"] = { "S":str(self.stack.docker_username) }

        if self.stack.ecr_repository_uri:
            item["ecr_repository_uri"] = { "S":str(self.stack.ecr_repository_uri) }
            ecr_uri = self.stack.ecr_repository_uri
        elif self.stack.ecr_repo_name:
            # ecr is primary and should be set
            ecr_uri = self._get_ecr_uri()
            item["ecr_repository_uri"] = { "S":str(ecr_uri) }

        if not ecr_uri:
            failed_message = "need to specify either ecr_repository_uri or ecr_repo_name to look up"
            raise Exception(failed_message)

        # if ecr_repo_name not set, we take it from the ecr_repository_uri
        if self.stack.ecr_repo_name:
            item["ecr_repo_name"] = { "S":str(self.stack.ecr_repo_name) }
        else:
            repo_name = str(ecr_uri.split("/")[-1])
            item["ecr_repo_name"] = { "S":str(repo_name) }

        # if docker_repository_uri not set, we set to ecr_repository_uri
        if self.stack.docker_repository_uri:
            item["docker_repository_uri"] = { "S":str(self.stack.docker_repository_uri) }
        elif ecr_uri:
            item["docker_repository_uri"] = item["ecr_repository_uri"]

        if self.stack.docker_repo_name:
            item["docker_repo_name"] = { "S":str(self.stack.docker_repo_name) }
        else:
            repo_name = str(item["docker_repository_uri"]["S"].split("/")[-1])
            item["docker_repo_name"] = { "S":str(repo_name) }

    def _get_dynamodb_item(self):

        suffix_id = self._determine_suffix_id()
        self._set_ssm_keys()

        s3_bucket = self._get_s3_bucket()
        s3_bucket_tmp = "{}-tmp".format(s3_bucket)

        self._set_codebuild_buckets()

        item = { "_id":{"S": str(self.stack.trigger_id) },
                 "ci_environment":{"S": str(self.stack.ci_environment) },
                 "codebuild_name":{"S": str(self.stack.codebuild_name) },
                 "git_repo":{"S": str(self.stack.git_repo) },
                 "git_url":{"S": str(self.stack.git_url) },
                 "privileged_mode":{"S": str(self.stack.privileged_mode) },
                 "image_type":{"S": str(self.stack.image_type) },
                 "build_image":{"S": str(self.stack.build_image) },
                 "build_timeout":{"S": str(self.stack.build_timeout) },
                 "compute_type":{"S": str(self.stack.compute_type) },
                 "docker_registry":{"S": str(self.stack.docker_registry) },
                 "aws_default_region":{"S": str(self.stack.aws_default_region) },
                 "trigger_id":{"S": str(self.stack.trigger_id) },
                 "secret":{"S": str(self.stack.secret) },
                 "ssm_ssh_key":{"S": str(self.stack.ssm_ssh_key) },
                 "ssm_callback_key":{"S": str(self.stack.ssm_callback_token) },
                 "s3_bucket":{"S": str(s3_bucket) },
                 "s3_bucket_tmp":{"S": str(s3_bucket_tmp) },
                 "s3_bucket_cache":{"S": str(self.s3_bucket_cache) },
                 "s3_bucket_output":{"S": str(self.s3_bucket_output) },
                 "suffix_id":{"S": str(suffix_id) },
                 "saas_env":{"S": str(self.stack.saas_env) },
                 "branch":{"S": str(self.stack.branch) },
                 "run_title":{"S": str(self.stack.run_title) }
                 }

        # additional credentials
        if self.stack.ssm_slack_webhook_hash: 
            item["ssm_slack_webhook_hash"] = { "S":str(self.stack.ssm_slack_webhook_hash) }

        if self.stack.slack_channel: 
            item["slack_channel"] = { "S":str(self.stack.slack_channel) }

        self._set_docker_items(item)
  
        # ed settings
        item["user_endpoint"] = { "S": str(self.stack.get_user_endpt()) }

        if hasattr(self.stack,"sched_name") and self.stack.sched_name:
            item["sched_name"] = { "S":str(self.stack.sched_name) }
            item["job_name"] = { "S":str(self.stack.sched_name) }
  
        if hasattr(self.stack,"schedule_id"): item["schedule_id"] = { "S":str(self.stack.schedule_id) }
        if hasattr(self.stack,"project_id"): item["project_id"] = { "S":str(self.stack.project_id) }
        if hasattr(self.stack,"job_instance_id"): item["job_instance_id"] = { "S":str(self.stack.job_instance_id) }
        if hasattr(self.stack,"cluster"): 
            item["cluster"] = { "S":str(self.stack.cluster) }
            item["project"] = { "S":str(self.stack.cluster) }
  
        ########################################################################################
        # TODO
        # revisit 54324345234535
        ########################################################################################
        item["sched_type"] = { "S":"build" }
  
        if hasattr(self.stack,"sched_type") and self.stack.sched_type != "build":
            self.stack.logger.warn('sched_type should be build, so overiding to display ci/commit info on UI')
  
        return self.stack.b64_encode(item)

    def _set_ssm_keys(self):

        self.stack.set_variable("ssm_docker_token",None)
        self.stack.set_variable("ssm_slack_webhook_hash",None)

        self.stack.set_variable("ssm_ssh_key","/codebuild/{}/sshkeys/private".format(self.stack.codebuild_name))
        self.stack.set_variable("ssm_callback_token","/codebuild/{}/ed/callback_token".format(self.stack.codebuild_name))

        if self.stack.inputvars.get("docker_token"):
            self.stack.set_variable("ssm_docker_token","/codebuild/{}/ed/docker_token".format(self.stack.codebuild_name))

        if self.stack.inputvars.get("slack_webhook_hash"):
            self.stack.set_variable("ssm_slack_webhook_hash","/codebuild/{}/ed/slack_webhook_hash".format(self.stack.codebuild_name))

    def _get_token(self):

        _lookup = {"must_be_one":True}
        _lookup["resource_type"] = "ed_token"
        _lookup["provider"] = "ed"
        _lookup["name"] = self.stack.codebuild_name

        return str(self.stack.get_resource(**_lookup)[0]["token"])

    def _token(self):

        self.stack.ed_token(name=self.stack.codebuild_name)

        return True

    def _dynamodb(self):

        table_name = "codebuild-shared-{}-{}".format(self.stack.ci_environment,"settings")
        item_hash = self._get_dynamodb_item()

        default_values = { "aws_default_region":self.stack.aws_default_region }

        overide_values = { "table_name": table_name,
                           "hash_key": "_id",
                           "item_hash": item_hash }

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "continuous_delivery"
        inputargs["human_description"] = 'Add setting item for codebuild name {}'.format(self.stack.codebuild_name)

        return self.stack.dynamodb.insert(display=True,**inputargs)

    def run_codebuild(self):

        self.stack.init_variables()
        self._set_ssm_keys()

        ssm_params = {"SSH_KEY": self.stack.ssm_ssh_key }

        if self.stack.ssm_docker_token: 
            ssm_params["DOCKER_TOKEN"] = self.stack.ssm_docker_token

        if self.stack.ssm_slack_webhook_hash: 
            ssm_params["SLACK_WEBHOOK_HASH"] = self.stack.ssm_slack_webhook_hash

        codebuild_env_vars = { "GIT_URL": self.stack.git_url }

        default_values = { "aws_default_region":self.stack.aws_default_region,
                           "codebuild_name": self.stack.codebuild_name }

        overide_values = { "docker_registry": self.stack.docker_registry }
        overide_values["ssm_params_hash"] = self.stack.b64_encode(ssm_params)

        overide_values["codebuild_env_vars_hash"] = self.stack.b64_encode(codebuild_env_vars)
        if self.stack.cloud_tags_hash: overide_values["cloud_tags_hash"] = self.stack.cloud_tags_hash

        # using tmp bucket for logs
        self._set_codebuild_buckets()

        overide_values["s3_bucket"] = "{}-tmp".format(self._get_s3_bucket())
        overide_values["s3_bucket_cache"] = self.s3_bucket_cache
        overide_values["s3_bucket_output"] = self.s3_bucket_output

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "continuous_delivery"
        inputargs["human_description"] = 'Create Codebuild project "{}"'.format(self.stack.codebuild_name)
    
        return self.stack.aws_codebuild.insert(display=True,**inputargs)

    def run(self):
    
        self.stack.unset_parallel()
        self.add_job("setup")
        self.add_job("ssm")
        self.add_job("codebuild")
        #self.add_job("webhook")

        return self.finalize_jobs()

    def schedule(self):

        sched = self.new_schedule()
        sched.job = "setup"
        sched.archive.timeout = 1800
        sched.archive.timewait = 120
        sched.conditions.retries = 1 
        sched.automation_phase = "continuous_delivery"
        sched.human_description = "Setup Basic for Codebuild"
        sched.on_success = [ "ssm" ]
        self.add_schedule()

        sched = self.new_schedule()
        sched.job = "ssm"
        sched.archive.timeout = 1800
        sched.archive.timewait = 120
        sched.automation_phase = "continuous_delivery"
        sched.human_description = 'Upload deploy key to ssm'
        sched.on_success = [ "codebuild" ]
        self.add_schedule()

        sched = self.new_schedule()
        sched.job = "codebuild"
        sched.archive.timeout = 1800
        sched.archive.timewait = 120
        sched.automation_phase = "continuous_delivery"
        sched.human_description = 'Create Codebuild Project'
        self.add_schedule()

        return self.get_schedules()
