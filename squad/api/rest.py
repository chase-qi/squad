import json
import yaml

from django.contrib.auth.models import Group as UserGroup
from squad.core.models import Group, Project, ProjectStatus, Build, TestRun, Environment, Test, Metric, EmailTemplate, KnownIssue, PatchSource, Suite
from squad.core.notification import Notification
from squad.ci.models import Backend, TestJob
from django.http import HttpResponse
from django.urls import reverse
from django import forms
from rest_framework import routers, serializers, views, viewsets, status
from rest_framework.decorators import detail_route
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.pagination import CursorPagination, PageNumberPagination

import rest_framework_filters as filters
from jinja2 import TemplateSyntaxError


class GroupFilter(filters.FilterSet):
    class Meta:
        model = Group
        fields = {'name': ['exact', 'in', 'startswith', 'contains', 'icontains'],
                  'slug': ['exact', 'in', 'startswith', 'contains', 'icontains']}


class ProjectFilter(filters.FilterSet):
    group = filters.RelatedFilter(GroupFilter, name="group", queryset=Group.objects.all())

    class Meta:
        model = Project
        fields = {'name': ['exact', 'in', 'startswith', 'contains', 'icontains'],
                  'slug': ['exact', 'in', 'startswith', 'contains', 'icontains'],
                  'id': ['exact', 'in']}


class EnvironmentFilter(filters.FilterSet):
    project = filters.RelatedFilter(ProjectFilter, name="project", queryset=Project.objects.all(), widget=forms.TextInput)

    class Meta:
        model = Environment
        fields = {'name': ['exact', 'in', 'startswith', 'contains', 'icontains'],
                  'slug': ['exact', 'in', 'startswith', 'contains', 'icontains'],
                  'id': ['exact']}


class ProjectStatusFilter(filters.FilterSet):

    class Meta:
        model = ProjectStatus
        fields = {'finished': ['exact', 'in'],
                  'approved': ['exact', 'in'],
                  'notified': ['exact', 'in'],
                  'has_metrics': ['exact', 'in'],
                  'last_updated': ['gt', 'lt']}


class BuildFilter(filters.FilterSet):
    project = filters.RelatedFilter(ProjectFilter, name="project", queryset=Project.objects.all(), widget=forms.TextInput)
    status = filters.RelatedFilter(ProjectStatusFilter, name="status", queryset=ProjectStatus.objects.all(), widget=forms.TextInput)

    class Meta:
        model = Build
        fields = {'version': ['exact', 'in', 'startswith'],
                  'id': ['exact']}


class TestRunFilter(filters.FilterSet):
    build = filters.RelatedFilter(BuildFilter, name="build", queryset=Build.objects.all(), widget=forms.TextInput)
    environment = filters.RelatedFilter(EnvironmentFilter, name="environment", queryset=Environment.objects.all(), widget=forms.TextInput)

    class Meta:
        model = TestRun
        fields = {'job_id': ['exact', 'in', 'startswith'],
                  'job_status': ['exact', 'in', 'startswith'],
                  'data_processed': ['exact', 'in'],
                  'status_recorded': ['exact', 'in']}


class TestJobFilter(filters.FilterSet):
    testrun = filters.RelatedFilter(TestRunFilter, name="testrun", queryset=TestRun.objects.all(), widget=forms.TextInput)
    target_build = filters.RelatedFilter(BuildFilter, name="target_build", queryset=Build.objects.all(), widget=forms.TextInput)

    class Meta:
        model = TestJob
        fields = {'name': ['exact', 'in', 'startswith', 'contains', 'icontains']}


class SuiteFilter(filters.FilterSet):
    project = filters.RelatedFilter(ProjectFilter, name="project", queryset=Project.objects.all(), widget=forms.TextInput)

    class Meta:
        model = Suite
        fields = {'name': ['exact', 'in', 'startswith', 'contains', 'icontains'],
                  'slug': ['exact', 'in', 'startswith', 'contains', 'icontains']}


class TestFilter(filters.FilterSet):
    test_run = filters.RelatedFilter(TestRunFilter, name="test_run", queryset=TestRun.objects.all(), widget=forms.TextInput)
    suite = filters.RelatedFilter(SuiteFilter, name="suite", queryset=Suite.objects.all(), widget=forms.TextInput)

    class Meta:
        model = Test
        fields = {'name': ['exact', 'in', 'startswith', 'contains', 'icontains'],
                  'result': ['exact', 'in']}


class API(routers.APIRootView):
    """
    Welcome to the SQUAD API. This API is self-describing, i.e. all of the
    available endpoints are accessible from this browseable user interface, and
    are self-describing themselves. See below for a list of them.

    Notes on the API:

    * All requests for lists of objects are paginated by default. Make sure you
      take the `count` and `next` fields of the response into account so you can
      navigate to the rest of the objects.

    * Only public projects are available through the API without
      authentication. Non-public projects require authentication using a valid
      API token, and the corresponding user account must also have access to
      the project in question.

    * All URLs displayed in this API browser are clickable.
    """

    def get_view_name(self):
        return "API"


class APIRouter(routers.DefaultRouter):

    APIRootView = API


class ModelViewSet(viewsets.ModelViewSet):

    def get_project_ids(self):
        """
        Determines which projects the current user is allowed to visualize.
        Returns a list of project ids to be used in get_queryset() for
        filtering.
        """
        user = self.request.user
        projects = Project.objects.accessible_to(user).values('id')
        return [p['id'] for p in projects]


class UserGroupSerializer(serializers.HyperlinkedModelSerializer):

    url = serializers.HyperlinkedIdentityField(view_name='usergroups-detail')

    class Meta:
        model = UserGroup
        fields = ('id', 'name', 'url')


class UserGroupViewSet(viewsets.ModelViewSet):
    """
    List of user groups.
    """
    queryset = UserGroup.objects
    serializer_class = UserGroupSerializer
    filter_fields = ('name',)
    search_fields = ('name',)
    ordering_fields = ('name',)


class GroupSerializer(serializers.HyperlinkedModelSerializer):

    id = serializers.IntegerField(read_only=True)
    user_groups = serializers.HyperlinkedRelatedField(
        many=True,
        queryset=UserGroup.objects.all(),
        view_name='usergroups-detail')

    class Meta:
        model = Group
        fields = '__all__'


class GroupViewSet(viewsets.ModelViewSet):
    """
    List of groups. Includes public groups and groups that the current
    user has access to.
    """
    queryset = Group.objects
    serializer_class = GroupSerializer
    filter_fields = ('slug', 'name')
    filter_class = GroupFilter
    search_fields = ('slug', 'name')
    ordering_fields = ('slug', 'name')

#    def get_queryset(self):
#        return self.queryset.accessible_to(self.request.user)


class ProjectSerializer(serializers.HyperlinkedModelSerializer):

    builds = serializers.HyperlinkedIdentityField(
        view_name='project-builds',
    )
    id = serializers.IntegerField(read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Project
        fields = '__all__'


class LatestTestResults(object):
    def __init__(self, build, test_name):
        self.build = build
        self.environments = build.project.environments.all()
        test_suite_name, test_case_name = test_name.split("/", 1)
        self.test_list = Test.objects.filter(
            test_run__build=self.build,
            test_run__environment__in=self.environments,
            name=test_case_name,
            suite__slug=test_suite_name)


class LatestTestResultsSerializer(serializers.BaseSerializer):
    def to_representation(self, obj):
        test_name = self.context.get('test_name')
        latest_result = LatestTestResults(obj, test_name)
        environments = []
        for environment in latest_result.environments.order_by("name", "slug"):
            test = latest_result.test_list.filter(test_run__environment=environment).first()
            entry = {
                'environment': EnvironmentSerializer(environment, context=self.context).data,
                'test': TestSerializer(test, context=self.context).data,
            }
            if test is not None:
                entry.update(
                    {'test_url_path': reverse(
                        'test_history',
                        args=[
                            latest_result.build.project.group.slug,
                            latest_result.build.project.slug,
                            test.full_name
                        ])}
                )
            environments.append(entry)
        serialized_obj = {
            'build': BuildSerializer(latest_result.build, context=self.context).data,
            'build_url_path': reverse(
                'build',
                args=[
                    latest_result.build.project.group.slug,
                    latest_result.build.project.slug,
                    latest_result.build.version
                ]),
            'environments': environments
        }
        return serialized_obj


class ProjectViewSet(viewsets.ModelViewSet):
    """
    List of projects. Includes public projects and projects that the current
    user has access to.
    """
    queryset = Project.objects
    serializer_class = ProjectSerializer
    filter_fields = ('group',
                     'slug',
                     'name',
                     'is_public',
                     'html_mail',
                     'custom_email_template',
                     'moderate_notifications',
                     'notification_strategy')
    filter_class = ProjectFilter
    search_fields = ('slug',
                     'name',)
    ordering_fields = ('slug',
                       'name',)

    def get_queryset(self):
        return self.queryset.accessible_to(self.request.user)

    @detail_route(methods=['get'], suffix='builds')
    def builds(self, request, pk=None):
        """
        List of builds for the current project.
        """
        builds = self.get_object().builds.prefetch_related('test_runs').order_by('-datetime')
        page = self.paginate_queryset(builds)
        serializer = BuildSerializer(page, many=True, context={'request': request})
        return self.get_paginated_response(serializer.data)

    @detail_route(methods=['get'], suffix='test_results')
    def test_results(self, request, pk=None):
        test_name = request.query_params.get("test_name", None)

        builds = self.get_object().builds.prefetch_related('test_runs').order_by('-datetime')
        page = self.paginate_queryset(builds)
        serializer = LatestTestResultsSerializer(
            page,
            many=True,
            context={'request': request, 'test_name': test_name}
        )
        return Response(serializer.data)


class ProjectStatusSerializer(serializers.HyperlinkedModelSerializer):

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if instance.regressions is not None:
            ret['regressions'] = json.dumps(yaml.load(ret['regressions']))
        if instance.fixes is not None:
            ret['fixes'] = json.dumps(yaml.load(ret['fixes']))
        return ret

    class Meta:
        model = ProjectStatus
        fields = ('last_updated',
                  'finished',
                  'notified',
                  'notified_on_timeout',
                  'approved',
                  'tests_pass',
                  'tests_fail',
                  'tests_skip',
                  'has_metrics',
                  'metrics_summary',
                  'build',
                  'created_at',
                  'regressions',
                  'fixes')


class ProjectStatusViewSet(viewsets.ModelViewSet):
    queryset = ProjectStatus.objects
    serializer_class = ProjectStatusSerializer
    filter_fields = ('build',)
    filter_class = ProjectStatusFilter

    ordering_fields = ('created_at', 'last_updated')


class PatchSourceSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = PatchSource
        fields = '__all__'
        extra_kwargs = {
            'token': {'write_only': True},
            'username': {'write_only': True}
        }


class PatchSourceViewSet(viewsets.ModelViewSet):
    queryset = PatchSource.objects
    serializer_class = PatchSourceSerializer
    filter_fields = ('implementation', 'url', 'name')


class BuildSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.IntegerField(read_only=True)
    testruns = serializers.HyperlinkedIdentityField(view_name='build-testruns')
    testjobs = serializers.HyperlinkedIdentityField(view_name='build-testjobs')
    status = serializers.HyperlinkedIdentityField(read_only=True, view_name='build-status', allow_null=True)
    metadata = serializers.HyperlinkedIdentityField(read_only=True, view_name='build-metadata')
    finished = serializers.BooleanField(read_only=True, source='status.finished')

    class Meta:
        model = Build
        fields = '__all__'


class BuildViewSet(ModelViewSet):
    """
    List of all builds in the system. Only builds belonging to public projects
    and to projects you have access to are available.
    """
    queryset = Build.objects.prefetch_related('status', 'test_runs').order_by('-datetime').all()
    serializer_class = BuildSerializer
    filter_fields = ('version', 'project')
    filter_class = BuildFilter
    search_fields = ('version',)
    ordering_fields = ('id', 'version', 'created_at', 'datetime')

    def get_queryset(self):
        return self.queryset.filter(project__in=self.get_project_ids())

    @detail_route(methods=['get'], suffix='metadata')
    def metadata(self, request, pk=None):
        build = self.get_object()
        return Response(build.metadata)

    @detail_route(methods=['get'], suffix='status')
    def status(self, request, pk=None):
        try:
            status = self.get_object().status
            serializer = ProjectStatusSerializer(status, many=False, context={'request': request})
            return Response(serializer.data)
        except ProjectStatus.DoesNotExist:
            raise NotFound()

    @detail_route(methods=['get'], suffix='test runs')
    def testruns(self, request, pk=None):
        testruns = self.get_object().test_runs.order_by('-id')
        page = self.paginate_queryset(testruns)
        serializer = TestRunSerializer(page, many=True, context={'request': request})
        return self.get_paginated_response(serializer.data)

    @detail_route(methods=['get'], suffix='test jobs')
    def testjobs(self, request, pk=None):
        testjobs = self.get_object().test_jobs.order_by('-id')
        page = self.paginate_queryset(testjobs)
        serializer = TestJobSerializer(page, many=True, context={'request': request})
        return self.get_paginated_response(serializer.data)

    @detail_route(methods=['get'], suffix='email')
    def email(self, request, pk=None):
        """
        This method produces the body of email notification for the build.
        By default it uses the project settings for HTML and template.
        These settings can be overwritten by using GET parameters:
         * output - sets the output format (text/plan, text/html)
         * template - sets the template used (id of existing template or
                      "default" for default SQUAD templates)
        """
        output_format = request.query_params.get("output", "text/plain")
        template_id = request.query_params.get("template", None)
        baseline_id = request.query_params.get("baseline", None)
        template = None
        if template_id != "default":
            template = self.get_object().project.custom_email_template
        if template_id is not None:
            try:
                template = EmailTemplate.objects.get(pk=template_id)
            except EmailTemplate.DoesNotExist:
                pass

        baseline = None
        if baseline_id is not None:
            try:
                previous_build = Build.objects.get(pk=baseline_id)
                baseline = previous_build.status
            except Build.DoesNotExist:
                data = {
                    "message": "Build %s does not exist" % baseline_id
                }
                return Response(data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except ProjectStatus.DoesNotExist:
                data = {
                    "message": "Build %s has no status" % baseline_id
                }
                return Response(data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if hasattr(self.get_object(), "status"):
            pr_status = self.get_object().status
            notification = Notification(pr_status, baseline)
            produce_html = self.get_object().project.html_mail
            if output_format == "text/html":
                produce_html = True
            try:
                txt, html = notification.message(produce_html, template)
                if len(html) > 0:
                    return HttpResponse(html, content_type=output_format)
                return HttpResponse(txt, content_type=output_format)
            except TemplateSyntaxError as e:
                data = {
                    "lineno": e.lineno,
                    "message": e.message
                }
                if template is not None:
                    data.update({
                        "txt": template.plain_text,
                        "html": template.html
                    })
                return Response(data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except TypeError as te:
                data = {"message": str(te)}
                if template is not None:
                    data.update({
                        "txt": template.plain_text,
                        "html": template.html
                    })
                return Response(data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({}, status=status.HTTP_404_NOT_FOUND)


class EnvironmentSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Environment
        fields = '__all__'


class EnvironmentViewSet(ModelViewSet):
    """
    List of environments. Only environments belonging to public projects and
    projects you have access to are available.
    """
    queryset = Environment.objects
    serializer_class = EnvironmentSerializer
    filter_fields = ('project', 'slug', 'name')
    filter_class = EnvironmentFilter
    search_fields = ('slug', 'name')
    ordering_fields = ('id', 'slug', 'name')

    def get_queryset(self):
        return self.queryset.filter(project__in=self.get_project_ids())


class TestRunSerializer(serializers.HyperlinkedModelSerializer):

    id = serializers.IntegerField(read_only=True)
    tests_file = serializers.HyperlinkedIdentityField(view_name='testrun-tests-file')
    metrics_file = serializers.HyperlinkedIdentityField(view_name='testrun-metrics-file')
    metadata_file = serializers.HyperlinkedIdentityField(view_name='testrun-metadata-file')
    log_file = serializers.HyperlinkedIdentityField(view_name='testrun-log-file')
    tests = serializers.HyperlinkedIdentityField(view_name='testrun-tests')
    metrics = serializers.HyperlinkedIdentityField(view_name='testrun-metrics')

    class Meta:
        model = TestRun
        fields = '__all__'


class SuiteSerializer(serializers.ModelSerializer):

    class Meta:
        model = Suite
        exclude = ('metadata',)


class SuiteViewSet(viewsets.ModelViewSet):

    queryset = Suite.objects.all()
    serializer_class = SuiteSerializer
    filter_class = SuiteFilter


class TestSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='full_name', read_only=True)
    short_name = serializers.CharField(source='name')
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Test
        exclude = ('test_run',)


class TestViewSet(ModelViewSet):

    queryset = Test.objects.all()
    serializer_class = TestSerializer
    filter_class = TestFilter
    pagination_class = CursorPagination
    ordering = ('id',)

    def get_queryset(self):
        return self.queryset.filter(test_run__build__project__in=self.get_project_ids())


class MetricSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='full_name', read_only=True)
    measurement_list = serializers.ListField(read_only=True)

    class Meta:
        model = Metric
        exclude = ('id', 'suite', 'test_run', 'measurements')


class TestRunViewSet(ModelViewSet):
    """
    List of test runs. Test runs represent test executions of a given build on
    a given environment.

    Only test runs from public projects and from projects accessible to you are
    available.
    """
    queryset = TestRun.objects.order_by('-id')
    serializer_class = TestRunSerializer
    filter_fields = (
        "build",
        "completed",
        "job_status",
        "data_processed",
        "status_recorded",
        "environment",
    )
    filter_class = TestRunFilter
    search_fields = ('environment',)
    ordering_fields = ('id', 'created_at', 'environment', 'datetime')
    pagination_class = CursorPagination
    ordering = ('created_at',)

    def get_queryset(self):
        return self.queryset.filter(build__project__in=self.get_project_ids())

    @detail_route(methods=['get'])
    def tests_file(self, request, pk=None):
        testrun = self.get_object()
        return HttpResponse(testrun.tests_file, content_type='application/json')

    @detail_route(methods=['get'])
    def metrics_file(self, request, pk=None):
        testrun = self.get_object()
        return HttpResponse(testrun.metrics_file, content_type='application/json')

    @detail_route(methods=['get'])
    def metadata_file(self, request, pk=None):
        testrun = self.get_object()
        return HttpResponse(testrun.metadata_file, content_type='application/json')

    @detail_route(methods=['get'])
    def log_file(self, request, pk=None):
        testrun = self.get_object()
        return HttpResponse(testrun.log_file, content_type='text/plain')

    @detail_route(methods=['get'], suffix='tests')
    def tests(self, request, pk=None):
        testrun = self.get_object()
        tests = testrun.tests.prefetch_related('suite').order_by('id')
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(tests, request)
        serializer = TestSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    @detail_route(methods=['get'], suffix='metrics')
    def metrics(self, request, pk=None):
        testrun = self.get_object()
        metrics = testrun.metrics.prefetch_related('suite').order_by('id')
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(metrics, request)
        serializer = MetricSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)


class BackendSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Backend
        fields = '__all__'
        extra_kwargs = {
            'token': {'write_only': True}
        }


class BackendViewSet(viewsets.ModelViewSet):
    """
    List of CI backends used.
    """
    queryset = Backend.objects.all()
    serializer_class = BackendSerializer
    filter_fields = ('implementation_type', 'name', 'url')
    search_fields = ('implementation_type', 'name', 'url')
    ordering_fields = ('id', 'implementation_type', 'name', 'url')


class TestJobSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='testjob-detail')
    external_url = serializers.CharField(source='url', read_only=True)
    definition = serializers.HyperlinkedIdentityField(view_name='testjob-definition')

    class Meta:
        model = TestJob
        fields = '__all__'


class TestJobViewSet(ModelViewSet):
    """
    List of CI test jobs. Only testjobs for public projects, and for projects
    you have access to, are available.
    """
    queryset = TestJob.objects.prefetch_related('backend').order_by('-id')
    serializer_class = TestJobSerializer
    filter_fields = (
        "name",
        "environment",
        "submitted",
        "fetched",
        "fetch_attempts",
        "last_fetch_attempt",
        "failure",
        "can_resubmit",
        "resubmitted_count",
        "job_status",
        "backend",
        "target",
        "testrun",
    )
    filter_class = TestJobFilter
    search_fields = ("name", "environment", "last_fetch_attempt")
    ordering_fields = ("id", "name", "environment", "last_fetch_attempt")
    pagination_class = CursorPagination
    ordering = ('id',)

    def get_queryset(self):
        return self.queryset.filter(target_build__project__in=self.get_project_ids())

    @detail_route(methods=['get'], suffix='definition')
    def definition(self, request, pk=None):
        definition = self.get_object().definition
        return HttpResponse(definition, content_type='text/plain')


class EmailTemplateSerializer(serializers.HyperlinkedModelSerializer):

    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = EmailTemplate
        fields = '__all__'


class EmailTemplateViewSet(viewsets.ModelViewSet):
    """
    List of email templates used.
    """
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer
    filter_fields = ('name',)
    ordering_fields = ('name', 'id')


class KnownIssueSerializer(serializers.HyperlinkedModelSerializer):

    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = KnownIssue
        fields = '__all__'


class KnownIssueViewSet(viewsets.ModelViewSet):

    queryset = KnownIssue.objects.all()
    serializer_class = KnownIssueSerializer
    filter_fields = ('title', 'test_name', 'active', 'intermittent', 'environments')
    ordering_fields = ('title', 'id')


router = APIRouter()
router.register(r'groups', GroupViewSet)
router.register(r'usergroups', UserGroupViewSet, 'usergroups')
router.register(r'projects', ProjectViewSet)
router.register(r'builds', BuildViewSet)
router.register(r'testjobs', TestJobViewSet)
router.register(r'testruns', TestRunViewSet)
router.register(r'tests', TestViewSet)
router.register(r'suites', SuiteViewSet)
router.register(r'environments', EnvironmentViewSet)
router.register(r'backends', BackendViewSet)
router.register(r'emailtemplates', EmailTemplateViewSet)
router.register(r'knownissues', KnownIssueViewSet)
router.register(r'patchsources', PatchSourceViewSet)
