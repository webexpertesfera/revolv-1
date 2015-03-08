from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.generic import CreateView, DetailView, UpdateView
from django.views.generic.edit import FormView

from revolv.base.users import UserDataMixin
from revolv.lib.mailer import send_revolv_email
from revolv.payments.forms import CreditCardDonationForm
from revolv.payments.services import PaymentService
from revolv.project import forms
from revolv.project.models import Category, Project


class CreateProjectView(CreateView):
    """
    The view to create a new project. Redirects to the homepage upon success.

    Accessed through /project/create
    """
    model = Project
    template_name = 'project/edit_project.html'
    form_class = forms.ProjectForm

    def get_success_url(self):
        return reverse('ambassador:dashboard')

    def form_valid(self, form):
        new_project = Project.objects.create_from_form(form, self.request.user.revolvuserprofile)
        messages.success(self.request, new_project.title + ' has been created!')
        return super(CreateProjectView, self).form_valid(form)

    # sets context to be the create view, doesn't pass in the id
    def get_context_data(self, **kwargs):
        context = super(CreateProjectView, self).get_context_data(**kwargs)
        context['action'] = reverse('project:new')
        context['categories'] = Category.category_list
        context['GOOGLEMAPS_API_KEY'] = settings.GOOGLEMAPS_API_KEY
        return context


class UpdateProjectView(UpdateView):
    """
    The view to update a project. It is the same view as creating a new
    project, though it prepopulates the existing field and passes in the
    project id. Redirects to the project page upon success.

    Accessed through /project/edit/{project_id}
    """
    model = Project
    template_name = 'project/edit_project.html'
    form_class = forms.ProjectForm

    def get_success_url(self):
        messages.success(self.request, 'Project details updated')
        return reverse('project:view', kwargs={'pk': self.get_object().id})

    # sets context to be the edit view by providing in the model id
    def get_context_data(self, **kwargs):
        context = super(UpdateProjectView, self).get_context_data(**kwargs)
        context['categories'] = Category.category_list
        context['action'] = reverse('project:edit',
                                    kwargs={'pk': self.get_object().id})
        return context


class ReviewProjectView(UserDataMixin, UpdateView):
    """
    The view to review a project. Shows the same view as ProjectView, but at
    the top, has a button group through which an ambassador or admin can
    update the project status.

    Accessed through /project/review/{project_id}
    """
    model = Project
    template_name = 'project/review_project.html'
    form_class = forms.ProjectStatusForm

    def get_success_url(self):
        if self.is_administrator:
            return "%s?active_project=%d" % (reverse('administrator:dashboard'), self.get_object().id)
        else:
            return reverse('project:view', kwargs={'pk': self.get_object().id})

    # Checks the post request and updates the project_status
    def form_valid(self, form):
        project = self.object
        if '_approve' in self.request.POST:
            messages.success(self.request, project.title + ' has been approved')
            project.approve_project()
        elif '_propose' in self.request.POST:
            messages.success(self.request, project.title + ' is now pending approval')
            project.propose_project()
        elif '_deny' in self.request.POST:
            messages.info(self.request, project.title + ' has been denied')
            project.deny_project()
        elif '_complete' in self.request.POST:
            messages.success(self.request, project.title + ' has been completed')
            project.complete_project()
        elif '_incomplete' in self.request.POST:
            messages.info(self.request, project.title + ' has been marked as incomplete')
            project.mark_as_incomplete_project()
        elif '_repayment' in self.request.POST:
            repayment_amount = Decimal(self.request.POST['_repayment_amount'])
            PaymentService.create_repayment(self.user_profile, repayment_amount, project)
            messages.success(self.request, '$' + str(repayment_amount) + ' repaid by ' + project.org_name)
        return redirect(self.get_success_url())


class PostFundingUpdateView(UpdateView):
    """
    The view to send out post funding updates about a project after it has completed.

    Accessed through /project/{project_id}/update
    """
    model = Project
    template_name = 'project/post_funding_update.html'
    form_class = forms.PostFundingUpdateForm

    def get_success_url(self):
        return reverse('project:view', kwargs={'pk': self.get_object().id})


class ProjectView(UserDataMixin, DetailView):
    """
    The project view. Displays project details and allows for editing.

    Accessed through /project/{project_id}
    """
    model = Project
    template_name = 'project/project.html'

    # pass in Project and Maps API key
    def get_context_data(self, **kwargs):
        context = super(ProjectView, self).get_context_data(**kwargs)
        context['GOOGLEMAPS_API_KEY'] = settings.GOOGLEMAPS_API_KEY
        return context

    def dispatch(self, request, *args, **kwargs):
        # always populate self.user, etc
        super_response = super(ProjectView, self).dispatch(request, *args, **kwargs)
        project = self.get_object()
        if (project.is_active or project.is_completed or
                (self.user.is_authenticated() and (project.has_owner(self.user_profile) or self.is_administrator))):
            return super_response
        else:
            return self.deny_access()


class SubmitDonationView(UserDataMixin, FormView):
    form_class = CreditCardDonationForm
    model = Project

    def form_valid(self, form):
        project = Project.objects.get(pk=self.kwargs.get('pk'))
        form.process_payment(project, self.user)
        context = {}
        context['user'] = self.user
        context['project'] = project
        context['amount'] = form.cleaned_data.get('amount')
        send_revolv_email(
            'post_donation',
            context, [self.user.email]
        )
        return JsonResponse({
            'amount': form.data['amount'],
        })

    def form_invalid(self, form):
        return JsonResponse({
            'error': form.errors,
        }, status=400)
