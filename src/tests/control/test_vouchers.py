import datetime

from django.utils.timezone import now
from tests.base import SoupTest, extract_form_fields

from pretix.base.models import (
    Event, EventPermission, Item, ItemVariation, Organizer,
    OrganizerPermission, Quota, User, Voucher,
)


class VoucherFormTest(SoupTest):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('dummy@dummy.dummy', 'dummy')
        self.orga = Organizer.objects.create(name='CCC', slug='ccc')
        self.event = Event.objects.create(
            organizer=self.orga, name='30C3', slug='30c3',
            date_from=datetime.datetime(2013, 12, 26, tzinfo=datetime.timezone.utc),
        )
        OrganizerPermission.objects.create(organizer=self.orga, user=self.user)
        EventPermission.objects.create(event=self.event, user=self.user, can_change_vouchers=True,
                                       can_change_settings=True)
        self.client.login(email='dummy@dummy.dummy', password='dummy')

        self.quota_shirts = Quota.objects.create(event=self.event, name='Shirts', size=2)
        self.shirt = Item.objects.create(event=self.event, name='T-Shirt', default_price=12)
        self.quota_shirts.items.add(self.shirt)
        self.shirt_red = ItemVariation.objects.create(item=self.shirt, default_price=14, value='Red')
        self.shirt_blue = ItemVariation.objects.create(item=self.shirt, value='Blue')
        self.quota_shirts.variations.add(self.shirt_red)
        self.quota_shirts.variations.add(self.shirt_blue)
        self.quota_tickets = Quota.objects.create(event=self.event, name='Tickets', size=5)
        self.ticket = Item.objects.create(event=self.event, name='Early-bird ticket',
                                          default_price=23)
        self.quota_tickets.items.add(self.ticket)

    def _create_voucher(self, data, expected_failure=False):
        count_before = self.event.vouchers.count()
        doc = self.get_doc('/control/event/%s/%s/vouchers/add' % (self.orga.slug, self.event.slug))
        form_data = extract_form_fields(doc.select('.container-fluid form')[0])
        form_data.update(data)
        doc = self.post_doc('/control/event/%s/%s/vouchers/add' % (self.orga.slug, self.event.slug), form_data)
        if expected_failure:
            assert doc.select(".alert-danger")
            assert count_before == self.event.vouchers.count()
        else:
            assert doc.select(".alert-success")
            assert count_before + 1 == self.event.vouchers.count()

    def _create_bulk_vouchers(self, data, expected_failure=False):
        count_before = self.event.vouchers.count()
        doc = self.get_doc('/control/event/%s/%s/vouchers/bulk_add' % (self.orga.slug, self.event.slug))
        form_data = extract_form_fields(doc.select('.container-fluid form')[0])
        form_data.update(data)
        doc = self.post_doc('/control/event/%s/%s/vouchers/bulk_add' % (self.orga.slug, self.event.slug), form_data)
        if expected_failure:
            assert doc.select(".alert-danger")
            assert count_before == self.event.vouchers.count()
        else:
            assert doc.select(".alert-success")
            assert count_before + len(form_data.get('codes').split("\n")) == self.event.vouchers.count()

    def _change_voucher(self, v, data, expected_failure=False):
        doc = self.get_doc('/control/event/%s/%s/vouchers/%s/' % (self.orga.slug, self.event.slug, v.pk))
        form_data = extract_form_fields(doc.select('.container-fluid form')[0])
        form_data.update(data)
        doc = self.post_doc('/control/event/%s/%s/vouchers/%s/' % (self.orga.slug, self.event.slug, v.pk), form_data)
        if expected_failure:
            assert doc.select(".alert-danger")
        else:
            assert doc.select(".alert-success")

    def test_create_non_blocking_item_voucher(self):
        self._create_voucher({
            'itemvar': '%d' % self.ticket.pk
        })
        v = Voucher.objects.latest('pk')
        assert not v.block_quota
        assert v.item.pk == self.ticket.pk
        assert v.variation is None
        assert v.quota is None

    def test_create_non_blocking_variation_voucher(self):
        self._create_voucher({
            'itemvar': '%d-%d' % (self.shirt.pk, self.shirt_red.pk)
        })
        v = Voucher.objects.latest('pk')
        assert not v.block_quota
        assert v.item.pk == self.shirt.pk
        assert v.variation.pk == self.shirt_red.pk
        assert v.quota is None

    def test_create_non_blocking_quota_voucher(self):
        self._create_voucher({
            'itemvar': 'q-%d' % self.quota_tickets.pk
        })
        v = Voucher.objects.latest('pk')
        assert not v.block_quota
        assert v.item is None
        assert v.variation is None
        assert v.quota.pk == self.quota_tickets.pk

    def test_create_blocking_item_voucher_quota_free(self):
        self._create_voucher({
            'itemvar': '%d' % self.ticket.pk,
            'block_quota': 'on'
        })
        v = Voucher.objects.latest('pk')
        assert v.block_quota

    def test_create_blocking_item_voucher_quota_full(self):
        self._create_voucher({
            'itemvar': '%d' % self.shirt.pk,
            'block_quota': 'on'
        }, expected_failure=True)

    def test_create_blocking_item_voucher_quota_full_invalid(self):
        self.quota_shirts.size = 0
        self.quota_shirts.save()
        self._create_voucher({
            'itemvar': '%d-%d' % (self.shirt.pk, self.shirt_red.pk),
            'block_quota': 'on',
            'valid_until': (now() - datetime.timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
        })

    def test_create_blocking_variation_voucher_quota_free(self):
        self._create_voucher({
            'itemvar': '%d-%d' % (self.shirt.pk, self.shirt_red.pk),
            'block_quota': 'on'
        })
        v = Voucher.objects.latest('pk')
        assert v.block_quota

    def test_create_blocking_variation_voucher_quota_full(self):
        self.quota_shirts.size = 0
        self.quota_shirts.save()
        self._create_voucher({
            'itemvar': '%d-%d' % (self.shirt.pk, self.shirt_red.pk),
            'block_quota': 'on'
        }, expected_failure=True)

    def test_create_blocking_quota_voucher_quota_free(self):
        self._create_voucher({
            'itemvar': 'q-%d' % self.quota_tickets.pk,
            'block_quota': 'on'
        })
        v = Voucher.objects.latest('pk')
        assert v.block_quota

    def test_create_blocking_quota_voucher_quota_full(self):
        self.quota_tickets.size = 0
        self.quota_tickets.save()
        self._create_voucher({
            'itemvar': 'q-%d' % self.quota_tickets.pk,
            'block_quota': 'on'
        }, expected_failure=True)

    def test_change_non_blocking_voucher(self):
        v = self.event.vouchers.create(item=self.ticket)
        self._change_voucher(v, {
            'itemvar': 'q-%d' % self.quota_tickets.pk
        })
        v.refresh_from_db()
        assert v.item is None
        assert v.variation is None
        assert v.quota.pk == self.quota_tickets.pk

    def test_change_blocking_voucher_unchanged_quota_full(self):
        self.quota_tickets.size = 0
        self.quota_tickets.save()
        v = self.event.vouchers.create(item=self.ticket, block_quota=True)
        self._change_voucher(v, {
        })
        v.refresh_from_db()
        assert v.block_quota

    def test_change_voucher_to_blocking_quota_full(self):
        self.quota_tickets.size = 0
        self.quota_tickets.save()
        v = self.event.vouchers.create(item=self.ticket)
        self._change_voucher(v, {
            'block_quota': 'on'
        }, expected_failure=True)

    def test_change_voucher_to_blocking_quota_free(self):
        v = self.event.vouchers.create(item=self.ticket)
        self._change_voucher(v, {
            'block_quota': 'on'
        })
        v.refresh_from_db()
        assert v.block_quota

    def test_change_voucher_validity_to_valid_quota_full(self):
        self.quota_tickets.size = 0
        self.quota_tickets.save()
        v = self.event.vouchers.create(item=self.ticket, valid_until=now() - datetime.timedelta(days=3),
                                       block_quota=True)
        self._change_voucher(v, {
            'valid_until': (now() + datetime.timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
        }, expected_failure=True)
        v.refresh_from_db()
        assert v.valid_until < now()

    def test_change_voucher_validity_to_valid_quota_free(self):
        v = self.event.vouchers.create(item=self.ticket, valid_until=now() - datetime.timedelta(days=3),
                                       block_quota=True)
        self._change_voucher(v, {
            'valid_until': (now() + datetime.timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
        })
        v.refresh_from_db()
        assert v.valid_until > now()

    def test_change_item_of_blocking_voucher_quota_free(self):
        ticket2 = Item.objects.create(event=self.event, name='Late-bird ticket', default_price=23)
        self.quota_tickets.items.add(ticket2)
        v = self.event.vouchers.create(item=self.ticket, block_quota=True)
        self._change_voucher(v, {
            'itemvar': '%d' % ticket2.pk,
        })

    def test_change_item_of_blocking_voucher_quota_full(self):
        self.quota_shirts.size = 0
        self.quota_shirts.save()
        hoodie = Item.objects.create(event=self.event, name='Hoodie', default_price=23)
        self.quota_shirts.items.add(hoodie)
        v = self.event.vouchers.create(item=self.ticket, block_quota=True)
        self._change_voucher(v, {
            'itemvar': '%d' % hoodie.pk,
        }, expected_failure=True)

    def test_change_variation_of_blocking_voucher_quota_free(self):
        self.quota_shirts.variations.remove(self.shirt_blue)
        self.quota_tickets.variations.add(self.shirt_blue)
        v = self.event.vouchers.create(item=self.shirt, variation=self.shirt_red, block_quota=True)
        self._change_voucher(v, {
            'itemvar': '%d-%d' % (self.shirt.pk, self.shirt_blue.pk),
        })

    def test_change_variation_of_blocking_voucher_quota_full(self):
        self.quota_shirts.variations.remove(self.shirt_blue)
        self.quota_tickets.variations.add(self.shirt_blue)
        self.quota_tickets.size = 0
        self.quota_tickets.save()
        v = self.event.vouchers.create(item=self.shirt, variation=self.shirt_red, block_quota=True)
        self._change_voucher(v, {
            'itemvar': '%d-%d' % (self.shirt.pk, self.shirt_blue.pk),
        }, expected_failure=True)

    def test_change_quota_of_blocking_voucher_quota_free(self):
        v = self.event.vouchers.create(quota=self.quota_tickets, block_quota=True)
        self._change_voucher(v, {
            'itemvar': 'q-%d' % self.quota_shirts.pk,
        })

    def test_change_quota_of_blocking_voucher_quota_full(self):
        self.quota_shirts.size = 0
        self.quota_shirts.save()
        v = self.event.vouchers.create(quota=self.quota_tickets, block_quota=True)
        self._change_voucher(v, {
            'itemvar': 'q-%d' % self.quota_shirts.pk,
        }, expected_failure=True)

    def test_change_item_of_blocking_voucher_without_quota_change(self):
        self.quota_tickets.size = 0
        self.quota_tickets.save()
        ticket2 = Item.objects.create(event=self.event, name='Standard Ticket', default_price=23)
        self.quota_tickets.items.add(ticket2)
        v = self.event.vouchers.create(item=self.ticket, block_quota=True)
        self._change_voucher(v, {
            'itemvar': '%d' % ticket2.pk,
        })

    def test_change_variation_of_blocking_voucher_without_quota_change(self):
        self.quota_shirts.size = 0
        self.quota_shirts.save()
        v = self.event.vouchers.create(item=self.shirt, variation=self.shirt_red, block_quota=True)
        self._change_voucher(v, {
            'itemvar': '%d-%d' % (self.shirt.pk, self.shirt_blue.pk),
        })

    def test_create_duplicate_code(self):
        v = self.event.vouchers.create(quota=self.quota_tickets)
        self._create_voucher({
            'code': v.code,
        }, expected_failure=True)

    def test_change_code_to_duplicate(self):
        v1 = self.event.vouchers.create(quota=self.quota_tickets)
        v2 = self.event.vouchers.create(quota=self.quota_tickets)
        self._change_voucher(v1, {
            'code': v2.code
        }, expected_failure=True)

    def test_create_bulk(self):
        self._create_bulk_vouchers({
            'codes': 'ABCDE\nDEFGH',
            'itemvar': '%d' % self.shirt.pk,
        })

    def test_create_blocking_bulk_quota_full(self):
        self.quota_tickets.size = 0
        self.quota_tickets.save()
        self._create_bulk_vouchers({
            'codes': 'ABCDE\nDEFGH',
            'itemvar': '%d' % self.ticket.pk,
            'block_quota': 'on'
        }, expected_failure=True)

    def test_create_blocking_bulk_quota_free(self):
        self.quota_tickets.size = 5
        self.quota_tickets.save()
        self._create_bulk_vouchers({
            'codes': 'ABCDE\nDEFGH',
            'itemvar': '%d' % self.ticket.pk,
            'block_quota': 'on'
        })

    def test_create_blocking_bulk_quota_partial(self):
        self.quota_tickets.size = 1
        self.quota_tickets.save()
        self._create_bulk_vouchers({
            'codes': 'ABCDE\nDEFGH',
            'itemvar': '%d' % self.ticket.pk,
            'block_quota': 'on'
        }, expected_failure=True)

    def test_create_bulk_with_duplicate_code(self):
        v = self.event.vouchers.create(quota=self.quota_tickets)
        self._create_bulk_vouchers({
            'codes': 'ABCDE\n%s' % v.code,
            'itemvar': '%d' % self.shirt.pk,
        }, expected_failure=True)
