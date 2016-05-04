# -*- coding: utf-8 -*-
"""
Created on Sun Mar 20 15:42:38 2016

@author: jonathan
"""
import os

from flask import Flask, render_template, redirect, url_for, request, session, flash
import datetime
import threading
from flask.ext.wtf import Form
from wtforms import StringField, IntegerField
from wtforms.validators import DataRequired, NumberRange

import time


from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site

from items import Chemical

import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.spider import Spider
from scrapy.http import Request
from twisted.internet import reactor
from scrapy.utils.project import get_project_settings

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

class MyPipeline(object):
    def process_item(self, item, spider):
        chemical_bin.append(dict(item))

settings = get_project_settings()
settings.overrides['ITEM_PIPELINES'] = {'__main__.MyPipeline': 1}

runner= CrawlerProcess(get_project_settings())
application = Flask(__name__)
resource = WSGIResource(reactor, reactor.getThreadPool(), application)
site = Site(resource)
port = int(os.environ.get('PORT', 5000))
reactor.listenTCP(port, site)



class CASSpider(Spider):                                                                        
    name = "cas2"
    start_urls = "https://pubchem.ncbi.nlm.nih.gov/"
       
    def __init__(self, chemical=None, chemical_info=None, selenium = None, *args, **kwargs):     
        super(CASSpider, self).__init__(*args, **kwargs)
        self.chemical = chemical
        self.chemical_info = chemical_info
        self.sel = selenium
    
    def start_requests(self):
        yield Request(self.start_urls, callback=self.parse, dont_filter=True)
        
    def parse(self,response):
        return scrapy.FormRequest.from_response(
            response,
            formdata={'term': self.chemical},
            callback=self.after_search
        )
    
    def after_search(self,response):
        if '/compound/' in response.url:
            return self.parseC(response)
        elif 'not found' in response.body:
            self.logger.info('Unknown Chemical %s', self.chemical)
            print "______ERRROR_____"
        else:
            return self.parseB(response)
                     
    def parseB(self,response):
        #### Chooses first link in response
        url = response.xpath('//div[2]/div/p/a/@href').extract()[0]   
        url = "https:" + url
        yield Request(url = url, callback = self.parseC)
        
    def parseC(self, response):
        chemical_item = Chemical()
        ###Create Item
        ###Name       
        name_url = response.url + "#section=Top"
        self.sel.get(name_url)
        time.sleep(4)
        chemical_item['name']= WebDriverWait(self.sel, 5).until(EC.presence_of_element_located((By.XPATH, '/html/body/main/div/div/div[1]/div[2]/div/h1/span'))).text
        ###CAS
        cas_url = response.url + "#section=CAS"
        self.sel.get(cas_url)
        time.sleep(1)                                                                                                           
        chemical_item['cas'] = WebDriverWait(self.sel, 5).until(EC.presence_of_element_located((By.XPATH,'//ol/li[3]/ol/li[3]/ol/li[1]/div[2]/div[1]'))).text
        ###GHS CLASSIFICATION
        hazard_url = response.url + "#section=GHS-Classification"
        self.sel.get(hazard_url)
        time.sleep(1)
        try:
            thumbnail_container = WebDriverWait(self.sel, 5).until(EC.presence_of_all_elements_located((By.XPATH,'//ol/li[1]/ol/li[1]/div[2]/div[1]/div/img')))
            urls = []        
            for element in thumbnail_container:
                urls.append(element.get_attribute('src'))
            chemical_item['image_urls']=urls
        except TimeoutException:
            chemical_item['image_urls']= [] 
        self.chemical_info.append(chemical_item)
        time.sleep(3)
        return chemical_item

    
class Amount(Form): 
    amount = IntegerField("Number of Chemicals for Label", validators =[DataRequired(), NumberRange(min=1, max = 7 , message = 'Number Out of Bounds')] )

class ChemicalForm(Form):
    labels = IntegerField("Number of Labels", validators = [DataRequired()])
    chemical = StringField("Chemical Name", validators=[DataRequired()])
    percent = StringField("Percent Amount", validators =[DataRequired(), NumberRange(min=1, max = 100)] )
    
class Preparer(Form):
    name = StringField("Prepared By", validators = [DataRequired()])

###FLASK START

@application.template_filter()
def datetimefilter(value, format='%Y/%m/%d %H:%M'):
    """convert a datetime to a different format."""
    return value.strftime(format)
    
application.jinja_env.filters['datetimefilter'] = datetimefilter



def template_test():
    form = Amount(csrf_enabled=False)
    if form.validate_on_submit() and request.method == "POST":
                session['amount'] = int(request.form['amount'])
                return redirect(url_for('.creator'))
    return render_template('home.html', title ="Home",current_time= datetime.datetime.now(), form=form)

application.add_url_rule('/', 'index', template_test, methods=['GET','POST'])


def creator():
    amount = session['amount']
    if 'chemical' in request.form:
        flash('Please Wait for Crawler to finish. If labels do not appear after 3 min, please reload')
        session['name'] = request.form['name'] 
        session['labels'] = int(request.form['labels'])
        f = request.form
        percent_list = f.getlist('percent')
        e = threading.Event()
        chemical_bin = []
        sel = webdriver.Firefox()
        def spiders(f,e,sel):
            for chemical in f:
                empty = []
                runner.crawl(CASSpider, chemical = chemical, chemical_info = empty, selenium = sel)
                chemical_bin.append(empty)
            d = runner.join()
            d.addBoth(lambda _: e.set())     
        t = threading.Thread(target = spiders, args =(f.getlist('chemical'),e, sel))
        t.start()
        e.wait()
        sel.close() 
        master_info = []
        hazard_urls = []
        counter = 0
        for chemical in chemical_bin:          
            c = chemical[0]
            if len(c['name']) > 10:
                c['name'] = c['name'][:10]
            else:
                spaces = 10 - len(c['name'])
                spaces = spaces * '_'
                c['name'] = c['name'] + spaces
            info = (c['name'].upper(),c['cas'] + ('_' *5), percent_list[counter]+ '%')
            master_info.append(info)
            for image in c['image_urls']:
                hazard_urls.append(image)
            counter += 1
        session['master_info']=master_info
        session['hazard_urls']= list(set(hazard_urls))
        return redirect(url_for('label'))
    chemform = ChemicalForm(csrf_enabled=False)
    nameform = Preparer(csrf_enabled = False)        
    return render_template('creator.html', title ="Results",current_time= datetime.datetime.now(), chemform=chemform, nameform=nameform, number_of_chemicals = amount) 

application.add_url_rule('/creator', 'creator', creator, methods=['GET','POST'])

def label():
    lines = len(session['master_info'])
    return render_template('test.html', amount = 1, master_info = session['master_info'] ,result = "test", name = session['name'],  lines = 7-lines, hazard_urls = session['hazard_urls'], labels = session['labels'])

application.add_url_rule('/label', 'label', label, methods=['GET','POST'])

if __name__ == "__main__":
    application.secret_key = 'super secret key'
    application.config['SESSION_TYPE'] = 'filesystem'
    application.config['SERVER_NAME']='localhost:5000'
    application.debug = True
    reactor.run()
    port = int(os.environ.get('PORT', 5000))   
    application.run(host='0.0.0.0', port=port)